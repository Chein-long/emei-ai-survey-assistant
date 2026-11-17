"""Persistent calculated plots shared by the dashboard and chat."""

from contextlib import closing
import hashlib
import json
import sqlite3

MODEL_NAMES = {"one_variable": "一元模型", "two_variable": "二元模型"}
SUMMARY_KEYS = {
    "Tree records": "tree_count",
    "Successful calculations": "successful",
    "Blocked calculations": "blocked",
    "AGB total": "AGB_total_kg",
    "AGC total": "AGC_total_kgC",
    "AGB area-based estimate": "AGB_Mg_ha",
    "AGC area-based estimate": "AGC_MgC_ha",
    "AGB successful subset": "AGB_subset_kg",
    "AGC successful subset": "AGC_subset_kgC",
}


def records(frame):
    return json.loads(frame.to_json(orient="records", force_ascii=False, double_precision=15))


def model_summary(summary, model_type):
    values = summary.set_index("Indicator")["Value"]
    return records(values.reindex(SUMMARY_KEYS).rename(index=SUMMARY_KEYS).to_frame().T)[0] | {
        "model": MODEL_NAMES[model_type]
    }


def make_snapshot(plot, trees, area, quality, issues):
    overview = {
        "plot_id": str(plot["plot_id"]).strip(),
        "forest_type": plot["forest_type"],
        "elevation_m": plot["elevation_m"],
        "plot_area_m2": area,
        "tree_count": len(trees),
        "dbh_mean_cm": trees["dbh_cm"].mean(),
        "height_mean_m": trees["height_m"].mean(),
    }
    import pandas as pd
    return {
        "overview": records(pd.DataFrame([overview]))[0] | {
            "species_counts": trees["species"].value_counts().to_dict(),
        },
        "quality": {
            "summary": dict(zip(quality["检查项目"], quality["检查结果"].astype(str))),
            "issues": records(issues),
            "issue_count": len(issues),
        },
    }


class PlotCatalog:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db, db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS plots (
                    plot_id TEXT PRIMARY KEY,
                    revision TEXT NOT NULL,
                    payload TEXT
                )
            """)

    def _connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def load(self):
        with closing(self._connect()) as db:
            return {
                plot_id: json.loads(payload) if payload is not None else None
                for plot_id, payload in db.execute("SELECT plot_id, payload FROM plots")
            }

    def save_model(self, snapshot, model_type, summary, trees, province):
        plot_id = snapshot["overview"]["plot_id"]
        # The same observations and review can keep both model results.
        # A new survey or province invalidates the previous model results.
        revision = hashlib.sha256(json.dumps(
            [snapshot, province, [
                {key: row[key] for key in (
                    "tree_id", "species", "dbh_raw_cm", "dbh_cm", "height_m",
                    "crown_ew_m", "crown_ns_m", "correction_status", "validation_status",
                )}
                for row in trees
            ]], ensure_ascii=False, sort_keys=True
        ).encode("utf-8")).hexdigest()

        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            old = db.execute(
                "SELECT revision, payload FROM plots WHERE plot_id = ?", (plot_id,)
            ).fetchone()
            models = json.loads(old[1])["models"] if old and old[0] == revision and old[1] else {}
            models[model_type] = {"summary": summary, "trees": trees}
            payload = snapshot | {"models": models}
            db.execute(
                "INSERT OR REPLACE INTO plots (plot_id, revision, payload) VALUES (?, ?, ?)",
                (plot_id, revision, json.dumps(payload, ensure_ascii=False, allow_nan=False)),
            )

    def delete(self, plot_id):
        with closing(self._connect()) as db, db:
            # Remember deletion so old bundled MC-1 workbooks cannot reappear.
            db.execute(
                "INSERT OR REPLACE INTO plots (plot_id, revision, payload) VALUES (?, '', NULL)",
                (plot_id,),
            )
