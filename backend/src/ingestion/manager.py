import os
import glob
import zipfile
import tempfile
import logging
from typing import Optional
import pandas as pd
from sqlalchemy.orm import Session
from .base import IngestionBase
from .processors.sleep import SleepProcessor
from .processors.activity import ActivityProcessor
from .processors.readiness import ReadinessProcessor
from .processors.common import CommonProcessor

# Configure Logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OuraParser")

class OuraParser(IngestionBase):
    def __init__(self, session: Session):
        super().__init__(session)
        self.sleep_processor = SleepProcessor(session)
        self.activity_processor = ActivityProcessor(session)
        self.readiness_processor = ReadinessProcessor(session)
        self.common_processor = CommonProcessor(session)

    def _find_csvs(self, dir_path: str, base_name: str) -> list:
        """Return all CSV paths matching base_name exactly or with a date-range suffix.

        Matches:
          sleep.csv
          sleep_2024-01-01_2024-12-31.csv
          sleep_2024-01-01.csv
        """
        stem = base_name[:-4] if base_name.endswith('.csv') else base_name
        exact = os.path.join(dir_path, f"{stem}.csv")
        dated = sorted(glob.glob(os.path.join(dir_path, f"{stem}_*.csv")))
        seen = set()
        results = []
        for p in ([exact] + dated):
            if p not in seen and os.path.exists(p):
                seen.add(p)
                results.append(p)
        return results

    def _read_csv_any(self, dir_path: str, base_name: str) -> Optional[pd.DataFrame]:
        """Read and concatenate all CSV files matching base_name (exact or date-ranged)."""
        paths = self._find_csvs(dir_path, base_name)
        if not paths:
            return None
        dfs = []
        for p in paths:
            df = self._read_csv_robust(p)
            if df is not None and not df.empty:
                logger.debug(f"Read {os.path.basename(p)}: {len(df)} rows")
                dfs.append(df)
        if not dfs:
            return None
        if len(dfs) == 1:
            return dfs[0]
        combined = pd.concat(dfs, ignore_index=True)
        logger.info(f"{base_name}: combined {len(paths)} files → {len(combined)} rows")
        return combined

    def parse_zip(self, zip_path: str):
        """Extracts ZIP and parses all contained CSVs, handling nested folders."""
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
            except zipfile.BadZipFile:
                logger.error(f"Error: Invalid ZIP file at {zip_path}")
                return

            # Recursively search for a directory containing data files
            target_dir = temp_dir
            found_csvs = []
            for root, dirs, files in os.walk(temp_dir):
                if any(f.startswith("dailysleep") or f.startswith("dailyactivity") for f in files):
                    target_dir = root
                    found_csvs = files
                    break

            if not found_csvs:
                logger.warning("No Oura CSV files found in the ZIP archive!")
            else:
                logger.info(f"Found data in: {target_dir}")

            self.parse_directory(target_dir)

    def parse_directory(self, dir_path: str):
        """Parses all supported CSV files in the directory, merging related files."""

        # --- 1. Sleep Data ---
        # Merge dailysleep + sleeptime + dailyspo2
        sleep_df = self._read_csv_any(dir_path, "dailysleep.csv")
        sleeptime_df = self._read_csv_any(dir_path, "sleeptime.csv")
        spo2_df = self._read_csv_any(dir_path, "dailyspo2.csv")

        merged_sleep = sleep_df

        if sleeptime_df is not None and not sleeptime_df.empty:
            if merged_sleep is not None and not merged_sleep.empty:
                if 'day' in merged_sleep.columns and 'day' in sleeptime_df.columns:
                    merged_sleep = pd.merge(merged_sleep, sleeptime_df, on='day', how='outer', suffixes=('', '_time'))
            else:
                merged_sleep = sleeptime_df

        if spo2_df is not None and not spo2_df.empty:
            if merged_sleep is not None and not merged_sleep.empty:
                if 'day' in merged_sleep.columns and 'day' in spo2_df.columns:
                    merged_sleep = pd.merge(merged_sleep, spo2_df, on='day', how='outer', suffixes=('', '_spo2'))
            else:
                merged_sleep = spo2_df

        if merged_sleep is not None and not merged_sleep.empty:
            logger.info("Processing Sleep Data...")
            self.sleep_processor.process_sleep(merged_sleep)

        # --- 2. Readiness Data ---
        readiness_df = self._read_csv_any(dir_path, "dailyreadiness.csv")
        stress_df = self._read_csv_any(dir_path, "dailystress.csv")

        if readiness_df is not None and not readiness_df.empty:
            if stress_df is not None and not stress_df.empty:
                if 'day' in readiness_df.columns and 'day' in stress_df.columns:
                    merged_readiness = pd.merge(readiness_df, stress_df, on='day', how='outer', suffixes=('', '_stress'))
                    logger.info("Processing Readiness Data...")
                    self.readiness_processor.process_readiness(merged_readiness)
                else:
                    self.readiness_processor.process_readiness(readiness_df)
            else:
                logger.info("Processing Readiness Data...")
                self.readiness_processor.process_readiness(readiness_df)
        elif stress_df is not None and not stress_df.empty:
            logger.info("Processing dailystress.csv as Readiness...")
            self.readiness_processor.process_readiness(stress_df)

        # --- 3. Activity & Other Data ---

        act_df = self._read_csv_any(dir_path, "dailyactivity.csv")
        if act_df is not None and not act_df.empty:
            logger.info("Processing Activity Data...")
            self.activity_processor.process_activity(act_df)

        res_df = self._read_csv_any(dir_path, "dailyresilience.csv")
        if res_df is not None and not res_df.empty:
            self.readiness_processor.process_resilience(res_df)

        day_stress_df = self._read_csv_any(dir_path, "daytimestress.csv")
        if day_stress_df is not None and not day_stress_df.empty:
            self.activity_processor.process_stress(day_stress_df)

        # --- 4. File-based processors (pass file path directly) ---
        path_map = {
            "sleep.csv": self.sleep_processor.process_sleep_session,
            "workout.csv": self.activity_processor.process_workout,
            "session.csv": self.activity_processor.process_meditation,
            "heartrate.csv": self.common_processor.process_heart_rate,
            "temperature.csv": self.common_processor.process_temperature,
        }

        for base_name, func in path_map.items():
            for fpath in self._find_csvs(dir_path, base_name):
                logger.info(f"Processing {os.path.basename(fpath)}...")
                func(fpath)

        # --- 5. DataFrame-based processors ---
        common_map = {
            "ringconfiguration.csv": self.common_processor.process_ring_configuration,
            "enhancedtag.csv": self.common_processor.process_tag,
            "tag.csv": self.common_processor.process_tag,
            "dailycardiovascularage.csv": self.common_processor.process_cardiovascular_age,
            "ringbatterylevel.csv": self.common_processor.process_ring_battery,
            "vo2max.csv": self.common_processor.process_vo2max,
        }

        for base_name, func in common_map.items():
            df = self._read_csv_any(dir_path, base_name)
            if df is not None and not df.empty:
                logger.info(f"Processing {base_name}...")
                func(df)
