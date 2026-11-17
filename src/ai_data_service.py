
from pathlib import Path
import argparse
import pandas as pd


# ============================================================
# 1. PROJECT PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

PROCESSED_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "data" / "outputs"

PLOT_FILE = PROCESSED_DIR / "MC-1_标准化数据.xlsx"
VALIDATION_FILE = PROCESSED_DIR / "MC-1_数据质量检查.xlsx"
COMPARISON_FILE = OUTPUT_DIR / "MC-1_一元与二元模型对照分析.xlsx"
DIAGNOSTIC_FILE = OUTPUT_DIR / "model_diagnostic.xlsx"


# ============================================================
# 2. DATA SERVICE
# ============================================================

class EmeiDataService:

    def __init__(self):

        print("正在初始化生态调查数据服务...")

        self.plot = self._read(PLOT_FILE, "Plot")
        self.trees = self._read(PLOT_FILE, "Trees")

        self.validation_summary = self._read(
            VALIDATION_FILE, "Validation_Summary"
        )

        self.validation_issues = self._read(
            VALIDATION_FILE, "Validation_Issues"
        )

        self.model_summary = self._read(
            COMPARISON_FILE, "模型汇总"
        )

        self.model_difference = self._read(
            COMPARISON_FILE, "模型差异"
        )

        self.tree_comparison = self._read(
            COMPARISON_FILE, "单株模型对照"
        )

        self.diagnostic_summary = self._read(
            DIAGNOSTIC_FILE, "诊断摘要"
        )

        self.top10 = self._read(
            DIAGNOSTIC_FILE, "差异最大的10株"
        )

        print("数据服务初始化完成。")

    # --------------------------------------------------------
    # Read Excel
    # --------------------------------------------------------

    @staticmethod
    def _read(file, sheet):

        if not file.exists():
            raise FileNotFoundError(
                f"找不到数据文件：{file}"
            )

        try:
            return pd.read_excel(
                file,
                sheet_name=sheet
            )

        except Exception as e:
            raise RuntimeError(
                f"读取失败：{file.name} / {sheet}\n{e}"
            )

    # --------------------------------------------------------
    # Convert pandas values into normal Python values
    # --------------------------------------------------------

    @staticmethod
    def _clean(value):

        if value is None or pd.isna(value):
            return None

        if hasattr(value, "item"):
            value = value.item()

        return value

    # --------------------------------------------------------
    # Find a value in a two-column table
    # --------------------------------------------------------

    @staticmethod
    def _lookup(df, key, key_col, value_col):

        matched = df.loc[
            df[key_col].astype(str).str.strip()
            == str(key).strip(),
            value_col
        ]

        if matched.empty:
            return None

        return EmeiDataService._clean(matched.iloc[0])

    # ========================================================
    # 3. PLOT OVERVIEW
    # ========================================================

    def get_plot_overview(self):

        plot = self.plot.iloc[0]

        dbh = pd.to_numeric(
            self.trees["dbh_cm"], errors="coerce"
        )

        height = pd.to_numeric(
            self.trees["height_m"], errors="coerce"
        )

        species_counts = (
            self.trees["species"]
            .value_counts()
            .to_dict()
        )

        return {
            "plot_id": self._clean(plot["plot_id"]),
            "forest_type": self._clean(plot["forest_type"]),
            "elevation_m": self._clean(plot["elevation_m"]),
            "plot_area_m2": self._clean(plot["plot_area_m2"]),
            "longitude": self._clean(plot["longitude"]),
            "latitude": self._clean(plot["latitude"]),
            "tree_count": int(len(self.trees)),
            "species_counts": species_counts,
            "dbh_mean_cm": self._clean(dbh.mean()),
            "dbh_min_cm": self._clean(dbh.min()),
            "dbh_max_cm": self._clean(dbh.max()),
            "height_mean_m": self._clean(height.mean()),
            "height_min_m": self._clean(height.min()),
            "height_max_m": self._clean(height.max())
        }

    # ========================================================
    # 4. DATA QUALITY
    # ========================================================

    def get_quality_summary(self):

        summary = {}

        for _, row in self.validation_summary.iterrows():

            key = str(row["检查项目"]).strip()

            summary[key] = self._clean(
                row["检查结果"]
            )

        issues = []

        for _, row in self.validation_issues.iterrows():

            issues.append({
                "tree_id": self._clean(row["树木编号"]),
                "field": self._clean(row["检查字段"]),
                "original_value": self._clean(row["原始值"]),
                "description": self._clean(row["问题描述"]),
                "review_status": self._clean(row["审核状态"]),
                "reviewer": self._clean(row["审核人员"]),
                "review_note": self._clean(row["审核说明"])
            })

        return {
            "summary": summary,
            "issues": issues,
            "issue_count": len(issues)
        }

    # ========================================================
    # 5. MODEL COMPARISON
    # ========================================================

    def get_model_comparison(self):

        models = []

        for _, row in self.model_summary.iterrows():

            models.append({
                "model": self._clean(row["模型"]),
                "tree_count": self._clean(row["乔木记录数"]),
                "successful": self._clean(row["成功数"]),
                "blocked": self._clean(row["阻断数"]),
                "AGB_total_kg": self._clean(row["AGB总量_kg"]),
                "AGC_total_kgC": self._clean(row["AGC总量_kgC"]),
                "AGB_Mg_ha": self._clean(row["单位面积AGB_Mg_ha"]),
                "AGC_MgC_ha": self._clean(row["单位面积AGC_MgC_ha"])
            })

        differences = []

        for _, row in self.model_difference.iterrows():

            differences.append({
                "indicator": self._clean(row["比较指标"]),
                "one_variable": self._clean(row["一元模型"]),
                "two_variable": self._clean(row["二元模型"]),
                "difference": self._clean(row["差值_二元减一元"]),
                "relative_difference_pct": self._clean(
                    row["相对差异_pct"]
                )
            })

        return {
            "models": models,
            "differences": differences
        }

    # ========================================================
    # 6. SINGLE TREE QUERY
    # ========================================================

    def get_tree_detail(self, tree_id):

        matched = self.tree_comparison.loc[
            self.tree_comparison["树木编号"]
            .astype(str).str.strip()
            == str(tree_id).strip()
        ]

        if matched.empty:
            return {
                "found": False,
                "message": f"没有找到乔木编号：{tree_id}"
            }

        row = matched.iloc[0]

        fields = [
            "树木编号",
            "树种",
            "胸径_cm",
            "树高_m",
            "数据审核状态",
            "一元AGB_kg",
            "一元AGC_kgC",
            "二元AGB_kg",
            "二元AGC_kgC",
            "AGB差值_kg",
            "AGB相对差异_pct",
            "一元规则编号",
            "二元规则编号",
            "对照状态"
        ]

        result = {}

        for field in fields:
            if field in row.index:
                result[field] = self._clean(row[field])

        result["found"] = True

        return result

    # ========================================================
    # 7. TOP DIFFERENCE TREES
    # ========================================================

    def get_top_differences(self, limit=10):

        limit = max(1, min(int(limit), 37))

        df = self.top10.head(limit)

        result = []

        for _, row in df.iterrows():

            result.append({
                "tree_id": self._clean(row["树木编号"]),
                "species": self._clean(row["树种"]),
                "dbh_cm": self._clean(row["胸径_cm"]),
                "height_m": self._clean(row["树高_m"]),
                "one_variable_AGB": self._clean(row["一元AGB_kg"]),
                "two_variable_AGB": self._clean(row["二元AGB_kg"]),
                "difference_kg": self._clean(row["AGB差值_kg"]),
                "relative_difference_pct": self._clean(
                    row["AGB相对差异_pct"]
                ),
                "contribution_pct": self._clean(
                    row["差异贡献比例_pct"]
                )
            })

        return result

    # ========================================================
    # 8. DIAGNOSTIC SUMMARY
    # ========================================================

    def get_diagnostic_summary(self):

        result = {}

        for _, row in self.diagnostic_summary.iterrows():

            key = str(row["诊断指标"]).strip()

            result[key] = self._clean(row["结果"])

        return result

    # ========================================================
    # 9. SELF TEST
    # ========================================================

    def self_test(self):

        print("\n========== AI DATA SERVICE SELF-TEST ==========")

        checks = []

        plot = self.get_plot_overview()
        quality = self.get_quality_summary()
        comparison = self.get_model_comparison()
        tree = self.get_tree_detail("MC-1-14")
        top10 = self.get_top_differences(10)
        diagnostic = self.get_diagnostic_summary()

        checks.append((
            "样地基本信息读取",
            plot["plot_id"] == "MC-1"
        ))

        checks.append((
            "37株乔木记录读取",
            plot["tree_count"] == 37
        ))

        checks.append((
            "数据质量记录读取",
            quality["issue_count"] == 2
        ))

        checks.append((
            "两种模型结果读取",
            len(comparison["models"]) == 2
        ))

        checks.append((
            "单株信息查询",
            tree.get("found") is True
        ))

        checks.append((
            "差异最大的10株读取",
            len(top10) == 10
        ))

        checks.append((
            "模型诊断摘要读取",
            len(diagnostic) > 0
        ))

        for name, passed in checks:

            status = "PASS" if passed else "FAIL"

            print(f"{status} | {name}")

        passed_count = sum(
            1 for _, passed in checks if passed
        )

        print("----------------------------------------------")
        print(
            f"自检结果：{passed_count}/{len(checks)}"
        )
        print("----------------------------------------------")

        if passed_count != len(checks):
            raise RuntimeError("数据服务自检未全部通过。")

        print("\n数据服务可以正常调用。")


# ============================================================
# 10. ENTRY POINT
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--self-test",
        action="store_true"
    )

    args = parser.parse_args()

    service = EmeiDataService()

    if args.self_test:
        service.self_test()

    else:
        print("\n数据服务已启动。")
        print("运行 --self-test 可以检查数据读取功能。")
