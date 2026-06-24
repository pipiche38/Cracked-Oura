import pandas as pd
import json
import uuid
import os
import logging
from datetime import datetime, date
from typing import List, Any, Type, Optional
from sqlalchemy.orm import Session
from sqlalchemy.dialects.sqlite import insert
from backend.src.models import Base

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("IngestionBase")

class IngestionBase:
    """
    Base class for Oura Data Ingestion.
    Provides robust CSV reading (handling bad quotes/mismatched columns) and batch upserting for SQLite.
    """
    def __init__(self, session: Session):
        self.session = session

    def _read_csv_robust(self, file_path: str) -> Optional[pd.DataFrame]:
        """Reads CSV using pandas, auto-detecting ; vs , delimiter."""
        if not os.path.exists(file_path):
            return None

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                first_line = f.readline()
        except Exception:
            return None

        if not first_line.strip():
            return None

        delimiter = ';' if ';' in first_line else ','
        filename = os.path.basename(file_path)
        logger.debug(f"[{filename}] detected delimiter: '{delimiter}'")

        try:
            df = pd.read_csv(
                file_path,
                sep=delimiter,
                encoding='utf-8',
                on_bad_lines='skip',
            )
        except Exception as e:
            logger.error(f"Error reading CSV {file_path}: {e}")
            return None

        if df is None or df.empty:
            logger.warning(f"[{filename}] empty or unreadable")
            return None

        logger.debug(f"[{filename}] {len(df)} rows, columns: {list(df.columns)}")
        self._clean_dataframe(df)
        return df

    def _clean_dataframe(self, df: pd.DataFrame):
        """Standardizes dataframe values (stripping extra quotes)."""
        for col in df.columns:
            df[col] = df[col].apply(lambda x: x.strip('"') if isinstance(x, str) else x)

    def _upsert(self, model: Type[Base], data: List[Any], index_elements: List[str]):
        """
        Generic SQLite upsert (INSERT OR REPLACE) implementation.
        """
        if not data:
            return

        # Convert ORM objects to dicts if needed
        if isinstance(data[0], model):
            clean_data = []
            for obj in data:
                row_dict = {}
                for col in model.__table__.columns:
                     val = getattr(obj, col.name)
                     row_dict[col.name] = val
                clean_data.append(row_dict)
            data = clean_data

        try:
            stmt = insert(model).values(data)

            # Columns to update on conflict (all except the index/primary key)
            update_dict = {col.name: col for col in stmt.excluded if col.name not in index_elements}

            if update_dict:
                stmt = stmt.on_conflict_do_update(
                    index_elements=index_elements,
                    set_=update_dict
                )
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=index_elements)

            self.session.execute(stmt)
            self.session.commit()
            logger.info(f"[{model.__tablename__}] upserted {len(data)} records")
        except Exception as e:
            self.session.rollback()
            logger.error(f"Error in _upsert for {model.__tablename__}: {e}")
            if data:
                logger.debug(f"First record sample: {data[0]}")
            raise e

    def _batch_upsert(self, model: Type[Base], data: List[Any], index_elements: List[str], batch_size=1000):
        """Batch upsert wrapper to avoid SQLite limit restrictions."""
        if not data:
            return

        total_records = len(data)
        logger.info(f"Upserting {total_records} records into {model.__tablename__}...")
        
        for i in range(0, total_records, batch_size):
            batch = data[i : i + batch_size]
            self._upsert(model, batch, index_elements)

    # --- Parsing Helpers ---

    def _parse_json_col(self, val):
        if pd.isna(val) or val == "" or val == 'null':
            return None
        if isinstance(val, str):
            try:
                # Handle CSV double-quote escaping
                val = val.replace('""', '"')
                if val.startswith('"') and val.endswith('"'):
                    val = val[1:-1]
                return json.loads(val)
            except json.JSONDecodeError:
                return None
        return val

    def _parse_datetime(self, val):
        if pd.isna(val) or val == "":
            return None
        if isinstance(val, str):
            val = val.replace('"', '')
        try:
            return pd.to_datetime(val, format='ISO8601').to_pydatetime()
        except:
            return None

    def _parse_date(self, val):
        if pd.isna(val) or val == "":
            return None
        if isinstance(val, date):
            return val
        if isinstance(val, str):
            val = val.replace('"', '')
        try:
            return pd.to_datetime(val).date()
        except:
            return None

    def _parse_float(self, val):
        if val is None or val == "":
            return None
        try:
            return float(val)
        except ValueError:
            return None

    def _parse_int(self, val):
        if val is None or val == "":
            return None
        try:
            # Handle "100.0" strings as 100
            return int(float(val))
        except ValueError:
            return None

    def _parse_sequence_to_timestamped_list(self, val, start_time: datetime, interval_seconds: int):
        """
        Robustly parses various sequence formats (JSON, AST, comma-separated) 
        into a uniform list of timestamped objects for the frontend.
        """
        if pd.isna(val) or val == "":
            return None
        
        if isinstance(val, (int, float)):
            val = str(int(val))

        items = None
        if isinstance(val, (dict, list)):
             if isinstance(val, dict) and 'items' in val:
                 items = val['items']
             elif isinstance(val, list):
                 items = val
        elif isinstance(val, str):
            val_str = val.strip()
            if not val_str:
                return None

            # Handle CSV double-quote escaping (e.g. ""key"" -> "key")
            val_str = val_str.replace('""', '"')
            if val_str.startswith('"') and val_str.endswith('"'):
                val_str = val_str[1:-1]

            # 1. JSON parse
            try:
                parsed = json.loads(val_str)
                if isinstance(parsed, dict) and 'items' in parsed:
                    items = parsed['items']
                elif isinstance(parsed, list):
                    items = parsed
            except json.JSONDecodeError:
                pass

            if items is None:
                # 2. Fallback: AST literal eval (only if it looks like a list)
                try:
                    if val_str.strip().startswith('['):
                        import ast
                        parsed = ast.literal_eval(val_str)
                        if isinstance(parsed, list):
                            items = parsed
                except:
                    pass

            if items is None:
                # 3. Fallback: Split/Clean (Handle digit strings "4422" or comma-separated)
                val_cleaned = val_str.replace('"', '').replace("'", "")
                if ',' in val_cleaned:
                        try:
                            items = [float(x.strip()) for x in val_cleaned.strip('[]').split(',') if x.strip()]
                        except:
                            pass
                else:
                    # Hypnogram string case: "4422233"
                    try:
                        items = [int(c) for c in val_cleaned if c.isdigit()]
                    except:
                        pass

        if not items:
            return None

        result = []
        for i, item in enumerate(items):
            ts = start_time + pd.Timedelta(seconds=i * interval_seconds)
            
            if isinstance(item, dict):
                val_to_store = item.copy()
                val_to_store['timestamp'] = ts.isoformat()
            else:
                val_to_store = {
                    "timestamp": ts.isoformat(),
                    "value": item
                }
            result.append(val_to_store)
            
        return result
