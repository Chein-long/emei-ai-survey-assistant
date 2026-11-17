
from pathlib import Path
import argparse
import math
import pandas as pd

from standard_rule_engine import (
    StandardRuleEngine,
    RuleEngineError
)


# ============================================================
# 1. PROJECT PATHS
# ============================================================

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "data" / "processed"
OUTPUT_DIR = ROOT / "data" / "outputs"

STANDARDIZED_FILE = DATA_DIR / "MC-1_标准化数据.xlsx"
VALIDATION_FILE = DATA_DIR / "MC-1_数据质量检查.xlsx"



# ============================================================
# 2. SUMMARY READER
# ============================================================

def build_summary_map(summary_df):

    if summary_df.empty or summary_df.shape[1] < 2:
        raise ValueError("Invalid Validation_Summary worksheet.")

    summary_map = {}

    for _, row in summary_df.iterrows():

        key = str(row.iloc[0]).strip()

        if not key or key.lower() == "nan":
            continue

        summary_map[key] = row.iloc[1]

    return summary_map


def get_summary_count(summary_map, label):

    if label not in summary_map:
        raise ValueError(
            f"Missing validation summary item: {label}"
        )

    value = pd.to_numeric(
        pd.Series([summary_map[label]]),
        errors="coerce"
    ).iloc[0]

    if pd.isna(value):
        raise ValueError(
            f"Invalid validation summary value: {label}"
        )

    value = float(value)

    if not math.isfinite(value) or value < 0:
        raise ValueError(
            f"Invalid validation count: {label}"
        )

    if not value.is_integer():
        raise ValueError(
            f"Validation count must be an integer: {label}"
        )

    return int(value)


# ============================================================
# 3. LOAD AND VALIDATE SOURCE DATA
# ============================================================

def load_validated_data(standardized_file=STANDARDIZED_FILE, validation_file=VALIDATION_FILE):

    if not standardized_file.exists():
        raise FileNotFoundError(
            f"Standardized workbook not found: {standardized_file}"
        )

    if not validation_file.exists():
        raise FileNotFoundError(
            f"Validation workbook not found: {validation_file}"
        )

    # --------------------------------------------------------
    # Read original plot information
    # --------------------------------------------------------

    plot_df = pd.read_excel(
        standardized_file,
        sheet_name="Plot",
        engine="openpyxl"
    )

    # --------------------------------------------------------
    # Read quality-controlled tree records
    # --------------------------------------------------------

    trees_df = pd.read_excel(
        validation_file,
        sheet_name="Trees_Checked",
        engine="openpyxl"
    )

    # --------------------------------------------------------
    # Read validation records
    # --------------------------------------------------------

    summary_df = pd.read_excel(
        validation_file,
        sheet_name="Validation_Summary",
        engine="openpyxl"
    )

    issues_df = pd.read_excel(
        validation_file,
        sheet_name="Validation_Issues",
        engine="openpyxl"
    )

    unmatched_df = pd.read_excel(
        validation_file,
        sheet_name="Unmatched_Reviews",
        engine="openpyxl"
    )

    # --------------------------------------------------------
    # Required fields
    # --------------------------------------------------------

    required_tree_columns = [
        "tree_id",
        "species",
        "dbh_cm",
        "height_m",
        "validation_status"
    ]

    missing = (
        set(required_tree_columns) - set(trees_df.columns)
    )

    if missing:
        raise ValueError(
            f"Missing tree fields: {sorted(missing)}"
        )

    required_plot_columns = [
        "plot_id",
        "plot_area_m2"
    ]

    missing = (
        set(required_plot_columns) - set(plot_df.columns)
    )

    if missing:
        raise ValueError(
            f"Missing plot fields: {sorted(missing)}"
        )

    required_issue_columns = [
        "问题等级",
        "树木编号",
        "审核状态"
    ]

    missing = (
        set(required_issue_columns) - set(issues_df.columns)
    )

    if missing:
        raise ValueError(
            f"Missing validation issue fields: {sorted(missing)}"
        )

    # --------------------------------------------------------
    # Plot information
    # --------------------------------------------------------

    if plot_df.empty or len(plot_df) != 1:
        raise ValueError(
            "Plot sheet must contain exactly one plot record."
        )

    plot = plot_df.iloc[0]

    area = pd.to_numeric(
        pd.Series([plot["plot_area_m2"]]),
        errors="coerce"
    ).iloc[0]

    if pd.isna(area) or not math.isfinite(float(area)) or area <= 0:
        raise ValueError("Invalid plot area.")

    area = float(area)

    if trees_df.empty:
        raise ValueError("No tree records found.")

    # --------------------------------------------------------
    # 1. Unique tree IDs
    # --------------------------------------------------------

    tree_ids = (
        trees_df["tree_id"]
        .astype("string")
        .str.strip()
    )

    if tree_ids.isna().any() or tree_ids.eq("").any():
        raise ValueError("Empty tree IDs detected.")

    if tree_ids.duplicated().any():
        raise ValueError("Duplicate tree IDs detected.")

    # --------------------------------------------------------
    # 2. Read validation summary
    # --------------------------------------------------------

    summary_map = build_summary_map(summary_df)

    reported_trees = get_summary_count(
        summary_map,
        "乔木记录总数"
    )

    blocking_count = get_summary_count(
        summary_map,
        "阻断问题数量"
    )

    warning_count = get_summary_count(
        summary_map,
        "统计警告总数"
    )

    pending_count = get_summary_count(
        summary_map,
        "待审核警告数量"
    )

    approved_count = get_summary_count(
        summary_map,
        "已确认正常数量"
    )

    correction_pending = get_summary_count(
        summary_map,
        "已修正待验证数量"
    )

    unmatched_count = get_summary_count(
        summary_map,
        "未匹配审核记录数量"
    )

    # --------------------------------------------------------
    # 3. Record count consistency
    # --------------------------------------------------------

    if reported_trees != len(trees_df):
        raise ValueError(
            "Tree record count does not match validation summary."
        )

    # --------------------------------------------------------
    # 4. Block unresolved issues
    # --------------------------------------------------------

    if blocking_count > 0:
        raise ValueError(
            f"{blocking_count} blocking issues remain."
        )

    if pending_count > 0:
        raise ValueError(
            f"{pending_count} warnings remain pending review."
        )

    if correction_pending > 0:
        raise ValueError(
            f"{correction_pending} corrected records "
            "remain unvalidated."
        )

    if unmatched_count > 0 or not unmatched_df.empty:
        raise ValueError(
            "Unmatched manual review records exist."
        )

    # --------------------------------------------------------
    # 5. Verify issue records
    # --------------------------------------------------------

    issue_levels = (
        issues_df["问题等级"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    issue_statuses = (
        issues_df["审核状态"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    issue_ids = (
        issues_df["树木编号"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    # All issue records must be warnings in this version
    unexpected_levels = set(issue_levels) - {"警告"}

    if unexpected_levels:
        raise ValueError(
            f"Unexpected issue levels: {unexpected_levels}"
        )

    actual_warning_count = int(
        (issue_levels == "警告").sum()
    )

    if actual_warning_count != warning_count:
        raise ValueError(
            "Warning count does not match Validation_Issues."
        )

    # Every warning must have an approved review
    approved_issue_count = int(
        (issue_statuses == "已确认正常").sum()
    )

    if approved_issue_count != approved_count:
        raise ValueError(
            "Approved review count does not match summary."
        )

    if approved_issue_count != warning_count:
        raise ValueError(
            "Not all warning records have been approved."
        )

    if not issue_ids.isin(tree_ids).all():
        raise ValueError(
            "Validation issue references an unknown tree ID."
        )

    # --------------------------------------------------------
    # 6. Check individual tree validation statuses
    # --------------------------------------------------------

    statuses = (
        trees_df["validation_status"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    allowed_statuses = {
        "通过",
        "已审核保留"
    }

    invalid_statuses = sorted(
        set(statuses) - allowed_statuses
    )

    if invalid_statuses:
        raise ValueError(
            f"Unapproved tree validation statuses: "
            f"{invalid_statuses}"
        )

    passed_count = int(
        (statuses == "通过").sum()
    )

    retained_ids = set(
        tree_ids.loc[
            statuses == "已审核保留"
        ]
    )

    approved_issue_ids = set(
        issue_ids.loc[
            issue_statuses == "已确认正常"
        ]
    )

    # Manually retained records must match approved issue records
    if retained_ids != approved_issue_ids:
        raise ValueError(
            "Manually retained tree IDs do not match "
            "approved review records."
        )

    # --------------------------------------------------------
    # 7. Final data admission
    # --------------------------------------------------------

    print("\n========== DATA VALIDATION GATE ==========")

    print("Total tree records:", len(trees_df))
    print("Passed records:", passed_count)
    print("Manually retained records:", len(retained_ids))
    print("Approved warning records:", approved_issue_count)
    print("Pending warnings:", pending_count)
    print("Blocking issues:", blocking_count)
    print("Unmatched reviews:", unmatched_count)

    print("Data admission: PASSED")

    return (
        plot,
        trees_df,
        area,
        summary_df,
        issues_df
    )


# ============================================================
# 4. BATCH BIOMASS CALCULATION
# ============================================================

def calculate_all_trees(
    trees_df,
    model_type="two_variable",
    *,
    province=None
):

    engine = StandardRuleEngine(province=province)

    results = []

    for _, row in trees_df.iterrows():

        # Preserve original survey information
        output = {

            "tree_id": row["tree_id"],

            "species": row["species"],

            "dbh_raw_cm": row.get("dbh_raw_cm"),

            "dbh_cm": row["dbh_cm"],

            "height_m": row["height_m"],

            "crown_ew_m": row.get("crown_ew_m"),

            "crown_ns_m": row.get("crown_ns_m"),

            "correction_status": row.get("correction_status"),

            "validation_status": row["validation_status"],

            "model_type": model_type,

            "standard_species_group": "",

            "population_scope": "",

            "dbh_class": "",

            "a0": None,

            "a1": None,

            "a2": None,

            "formula": "",

            "AGB_kg": None,

            "CF": None,

            "AGC_kgC": None,

            "rule_id": "",

            "standard_id": "",

            "source_table": "",

            "source_page": "",

            "carbon_source_table": "",

            "carbon_source_page": "",

            "calculation_status": "blocked",

            "error_message": ""
        }

        try:

            result = engine.calculate_tree(

                species_name=row["species"],

                dbh_cm=row["dbh_cm"],

                height_m=row["height_m"],

                model_type=model_type,

                tree_id=row["tree_id"]
            )

            output.update({

                "standard_species_group":
                    result["standard_species_group"],

                "population_scope":
                    result["population_scope"],

                "dbh_class":
                    result["dbh_class"],

                "a0":
                    result["a0"],

                "a1":
                    result["a1"],

                "a2":
                    result["a2"],

                "formula":
                    result["formula"],

                "AGB_kg":
                    result["AGB_kg"],

                "CF":
                    result["CF"],

                "AGC_kgC":
                    result["AGC_kgC"],

                "rule_id":
                    result["rule_id"],

                "standard_id":
                    result["standard_id"],

                "source_table":
                    result["source_table"],

                "source_page":
                    result["source_page"],

                "carbon_source_table":
                    result["carbon_source_table"],

                "carbon_source_page":
                    result["carbon_source_page"],

                "calculation_status": "success",

                "error_message": ""

            })

        except RuleEngineError as exc:

            output["error_message"] = str(exc)

        results.append(output)

    return pd.DataFrame(results)


# ============================================================
# 5. PLOT-LEVEL SUMMARY
# ============================================================

def generate_plot_summary(
    plot,
    results,
    area,
    model_type
):

    total_records = len(results)

    successful = results[
        results["calculation_status"] == "success"
    ]

    blocked = results[
        results["calculation_status"] == "blocked"
    ]

    complete = (
        total_records > 0
        and len(successful) == total_records
    )

    agb_sum = float(
        pd.to_numeric(
            successful["AGB_kg"],
            errors="coerce"
        ).sum()
    )

    agc_sum = float(
        pd.to_numeric(
            successful["AGC_kgC"],
            errors="coerce"
        ).sum()
    )

    # Convert kg/plot to Mg/ha
    expansion_factor = 10000 / area

    if complete:

        agb_plot = agb_sum

        agc_plot = agc_sum

        agb_ha = (
            agb_sum * expansion_factor / 1000
        )

        agc_ha = (
            agc_sum * expansion_factor / 1000
        )

    else:

        # Never report partial results as complete plot totals
        agb_plot = None

        agc_plot = None

        agb_ha = None

        agc_ha = None

    summary = [

        ["Plot ID", plot["plot_id"], ""],

        ["Forest type", plot["forest_type"], ""],

        ["Elevation", plot["elevation_m"], "m"],

        ["Plot area", area, "m2"],

        ["Area expansion factor",
         expansion_factor, "10000 / plot area"],

        ["Calculation model", model_type, ""],

        ["Tree records", total_records, "trees"],

        ["Successful calculations",
         len(successful), "trees"],

        ["Blocked calculations",
         len(blocked), "trees"],

        ["Calculation completeness",
         "Complete" if complete else "Incomplete", ""],

        ["AGB total", agb_plot, "kg / plot"],

        ["AGC total", agc_plot, "kg C / plot"],

        ["AGB area-based estimate",
         agb_ha, "Mg / ha"],

        ["AGC area-based estimate",
         agc_ha, "Mg C / ha"],

        ["AGB successful subset",
         agb_sum, "kg"],

        ["AGC successful subset",
         agc_sum, "kg C"]

    ]

    return pd.DataFrame(
        summary,
        columns=["Indicator", "Value", "Unit"]
    )


# ============================================================
# 6. EXPORT EXCEL REPORT
# ============================================================

def export_report(
    plot,
    results,
    summary,
    validation_summary,
    validation_issues,
    model_type,
    output_file
):

    metadata = pd.DataFrame([

        ["Project",
         "Emei AI Ecological Survey Assistant"],

        ["Plot ID",
         plot["plot_id"]],

        ["Input data",
         STANDARDIZED_FILE.name],

        ["Quality control source",
         VALIDATION_FILE.name],

        ["Calculation model",
         model_type],

        ["Biomass standard",
         "GB/T 43648-2024"],

        ["Carbon component",
         "Aboveground"],

        ["AGB unit",
         "kg/tree"],

        ["AGC unit",
         "kg C/tree"],

        ["Area-based unit",
         "Mg/ha"],

        ["Rule engine",
         "Standard Rule Engine V1.0"]

    ], columns=["Item", "Value"])

    errors = results[
        results["calculation_status"] == "blocked"
    ].copy()

    try:

        with pd.ExcelWriter(
            output_file,
            engine="openpyxl"
        ) as writer:

            results.to_excel(
                writer,
                sheet_name="Tree_Biomass",
                index=False
            )

            summary.to_excel(
                writer,
                sheet_name="Plot_Summary",
                index=False
            )

            metadata.to_excel(
                writer,
                sheet_name="Calculation_Metadata",
                index=False
            )

            errors.to_excel(
                writer,
                sheet_name="Calculation_Errors",
                index=False
            )

            validation_summary.to_excel(
                writer,
                sheet_name="Validation_Summary",
                index=False
            )

            validation_issues.to_excel(
                writer,
                sheet_name="Validation_Issues",
                index=False
            )

            # Basic Excel formatting
            for ws in writer.book.worksheets:

                ws.freeze_panes = "A2"

                ws.auto_filter.ref = ws.dimensions

                for column_cells in ws.columns:

                    column_letter = (
                        column_cells[0].column_letter
                    )

                    max_length = max(

                        len(str(cell.value or ""))

                        for cell in column_cells

                    )

                    ws.column_dimensions[
                        column_letter
                    ].width = min(
                        max(max_length + 2, 12),
                        35
                    )

    except PermissionError:

        raise PermissionError(
            "Output workbook is occupied. "
            "Close Excel or WPS and run again."
        )

    return output_file


# ============================================================
# 7. MAIN PROGRAM
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description="MC-1 Biomass and Carbon Calculator"
    )

    parser.add_argument(
        "--model",
        choices=[
            "one_variable",
            "two_variable"
        ],
        default="two_variable"
    )

    args = parser.parse_args()

    print("\n========== Biomass Calculator V1.1 ==========\n")

    # --------------------------------------------------------
    # Load validated data
    # --------------------------------------------------------

    (
        plot,
        trees,
        area,
        validation_summary,
        validation_issues
    ) = load_validated_data()

    print("\n---------- INPUT INFORMATION ----------")

    print("Plot ID:", plot["plot_id"])

    print("Tree records:", len(trees))

    print("Plot area:", area, "m2")

    print("Model:", args.model)

    # --------------------------------------------------------
    # Batch calculation
    # --------------------------------------------------------

    print("\n---------- BATCH CALCULATION ----------")

    results = calculate_all_trees(
        trees,
        model_type=args.model
    )

    # --------------------------------------------------------
    # Plot summary
    # --------------------------------------------------------

    summary = generate_plot_summary(
        plot,
        results,
        area,
        args.model
    )

    # --------------------------------------------------------
    # Export report
    # --------------------------------------------------------

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = (
        OUTPUT_DIR
        / f"MC-1_生物量与碳储量计算结果_{args.model}.xlsx"
    )

    export_report(
        plot,
        results,
        summary,
        validation_summary,
        validation_issues,
        args.model,
        output_file
    )

    # --------------------------------------------------------
    # Final report
    # --------------------------------------------------------

    successful = int(
        (
            results["calculation_status"] == "success"
        ).sum()
    )

    blocked = int(
        (
            results["calculation_status"] == "blocked"
        ).sum()
    )

    print("\n========== CALCULATION RESULTS ==========")

    print("Model:", args.model)

    print("Total trees:", len(results))

    print("Successful:", successful)

    print("Blocked:", blocked)

    print("\n========== PLOT SUMMARY ==========")

    print(
        summary.to_string(index=False)
    )

    print("\n========== OUTPUT ==========")

    print(
        str(output_file)
        .encode("unicode_escape")
        .decode("ascii")
    )

    if blocked > 0:

        print("\nWARNING: Some trees were not calculated.")

        print("Please inspect Calculation_Errors.")

    else:

        print("\nAll tree records calculated successfully.")

    print("\nBiomass Calculator V1.1 completed.")


# ============================================================
# 8. ENTRY POINT
# ============================================================

if __name__ == "__main__":

    main()
