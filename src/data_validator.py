
from pathlib import Path
import pandas as pd

from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter


# ==========================================
# 1. 项目路径
# ==========================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]

INPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "MC-1_标准化数据.xlsx"
)

REVIEW_FILE = (
    PROJECT_ROOT
    / "data"
    / "reviews"
    / "manual_reviews.csv"
)

OUTPUT_FILE = (
    PROJECT_ROOT
    / "data"
    / "processed"
    / "MC-1_数据质量检查.xlsx"
)


# ==========================================
# 2. 必要字段
# ==========================================

REQUIRED_COLUMNS = [
    "tree_id",
    "species",
    "height_m",
    "dbh_raw_cm",
    "dbh_cm",
    "correction_status",
    "correction_reason",
    "crown_raw",
    "crown_ew_m",
    "crown_ns_m",
    "crown_parse_status"
]

REVIEW_COLUMNS = [
    "tree_id",
    "check_field",
    "rule_id",
    "review_status",
    "reviewer",
    "review_date",
    "review_note"
]

ISSUE_COLUMNS = [
    "问题等级",
    "rule_id",
    "树木编号",
    "检查字段",
    "原始值",
    "问题描述",
    "处理建议"
]

REVIEW_RESULT_COLUMNS = [
    "审核状态",
    "审核人员",
    "审核日期",
    "审核说明"
]


# ==========================================
# 3. 记录问题
# ==========================================

def add_issue(
    issues,
    severity,
    rule_id,
    tree_id,
    field,
    original_value,
    description,
    suggestion
):

    issues.append({

        "问题等级": severity,

        "rule_id": rule_id,

        "树木编号": tree_id,

        "检查字段": field,

        "原始值": original_value,

        "问题描述": description,

        "处理建议": suggestion

    })


# ==========================================
# 4. IQR异常值筛查
# ==========================================

def detect_iqr_outliers(series):

    result = pd.Series(
        False,
        index=series.index
    )

    valid = series.dropna()

    if len(valid) < 8:
        return result

    q1 = valid.quantile(0.25)

    q3 = valid.quantile(0.75)

    iqr = q3 - q1

    if iqr <= 0:
        return result

    lower = q1 - 1.5 * iqr

    upper = q3 + 1.5 * iqr

    result = (
        (series < lower)
        | (series > upper)
    ).fillna(False)

    return result


# ==========================================
# 5. 主程序
# ==========================================

def main(input_file=INPUT_FILE, output_file=OUTPUT_FILE, review_file=REVIEW_FILE):

    # 检查文件

    if not input_file.exists():
        raise FileNotFoundError(
            f"找不到标准化数据：{input_file}"
        )

    if review_file is not None and not review_file.exists():
        raise FileNotFoundError(
            f"找不到人工审核记录：{review_file}"
        )

    # 读取标准化数据

    trees = pd.read_excel(
        input_file,
        sheet_name="Trees"
    )

    # 检查必要字段

    missing_columns = [
        col for col in REQUIRED_COLUMNS
        if col not in trees.columns
    ]

    if missing_columns:
        raise ValueError(
            f"标准化数据缺少字段：{missing_columns}"
        )

    # 整理文本字段

    text_columns = [
        "tree_id",
        "species",
        "correction_status",
        "correction_reason",
        "crown_raw",
        "crown_parse_status"
    ]

    for col in text_columns:
        trees[col] = (
            trees[col]
            .astype("string")
            .str.strip()
        )

    # 转换数值字段

    numeric_columns = [
        "height_m",
        "dbh_raw_cm",
        "dbh_cm",
        "crown_ew_m",
        "crown_ns_m"
    ]

    for col in numeric_columns:

        trees[col] = pd.to_numeric(
            trees[col],
            errors="coerce"
        )

    issues = []

    # ======================================
    # 6. 完整性和合法性检查
    # ======================================

    for idx, row in trees.iterrows():

        tree_id = row["tree_id"]

        if pd.isna(tree_id) or str(tree_id).strip() == "":
            tree_id = f"记录第{idx + 1}行"

            add_issue(
                issues, "阻断", "TREE_ID_MISSING",
                tree_id, "tree_id", None,
                "树木编号缺失",
                "补充正确的树木编号"
            )

        if pd.isna(row["species"]) or str(row["species"]).strip() == "":

            add_issue(
                issues, "阻断", "SPECIES_MISSING",
                tree_id, "species", None,
                "树种名称缺失",
                "补充树种名称"
            )

        if pd.isna(row["height_m"]):

            add_issue(
                issues, "阻断", "HEIGHT_MISSING",
                tree_id, "height_m", None,
                "树高缺失或无法转换为数字",
                "检查原始调查记录"
            )

        elif row["height_m"] <= 0:

            add_issue(
                issues, "阻断", "HEIGHT_NONPOSITIVE",
                tree_id, "height_m", row["height_m"],
                "树高必须大于0",
                "核对树高记录及单位"
            )

        if pd.isna(row["dbh_cm"]):

            add_issue(
                issues, "阻断", "DBH_MISSING",
                tree_id, "dbh_cm", None,
                "计算用胸径缺失",
                "补充胸径数据"
            )

        elif row["dbh_cm"] <= 0:

            add_issue(
                issues, "阻断", "DBH_NONPOSITIVE",
                tree_id, "dbh_cm", row["dbh_cm"],
                "胸径必须大于0",
                "核对胸径记录及单位"
            )

    # ======================================
    # 7. 重复编号检查
    # ======================================

    duplicate_mask = (
        trees["tree_id"].notna()
        & trees["tree_id"].duplicated(keep=False)
    )

    for idx in trees.index[duplicate_mask]:

        add_issue(
            issues, "阻断", "TREE_ID_DUPLICATE",
            trees.at[idx, "tree_id"],
            "tree_id",
            trees.at[idx, "tree_id"],
            "存在重复的树木编号",
            "核对是否重复录入"
        )

    # ======================================
    # 8. 胸径修正追溯检查
    # ======================================

    for idx, row in trees.iterrows():

        tree_id = row["tree_id"]

        raw_dbh = row["dbh_raw_cm"]

        final_dbh = row["dbh_cm"]

        status = row["correction_status"]

        reason = row["correction_reason"]

        if status == "人工确认修正":

            if pd.isna(raw_dbh):

                add_issue(
                    issues, "阻断", "DBH_RAW_MISSING",
                    tree_id, "dbh_raw_cm", None,
                    "人工修正记录缺少原始胸径",
                    "恢复原始调查记录"
                )

            if pd.isna(reason) or str(reason).strip() == "":

                add_issue(
                    issues, "阻断", "DBH_REASON_MISSING",
                    tree_id, "correction_reason", reason,
                    "人工修正没有保存原因",
                    "补充修正理由"
                )

        elif (
            pd.notna(raw_dbh)
            and pd.notna(final_dbh)
            and abs(raw_dbh - final_dbh) > 1e-9
        ):

            add_issue(
                issues, "阻断", "DBH_CHANGE_UNTRACKED",
                tree_id, "dbh_cm", final_dbh,
                "胸径发生变化但没有人工修正标记",
                "核实数据修正记录"
            )

    # ======================================
    # 9. 冠幅检查
    # ======================================

    for idx, row in trees.iterrows():

        tree_id = row["tree_id"]

        if (
            pd.isna(row["crown_parse_status"])
            or row["crown_parse_status"] != "成功"
        ):

            add_issue(
                issues, "警告", "CROWN_PARSE_FAILED",
                tree_id, "crown_raw",
                row["crown_raw"],
                "冠幅没有成功解析",
                "人工核对冠幅记录"
            )

        for col in ["crown_ew_m", "crown_ns_m"]:

            value = row[col]

            if pd.isna(value) or value <= 0:

                add_issue(
                    issues, "警告", "CROWN_VALUE_INVALID",
                    tree_id, col, value,
                    "冠幅缺失或不大于0",
                    "核对原始调查记录"
                )

    # ======================================
    # 10. IQR异常值检查
    # ======================================

    for col in ["dbh_cm", "height_m"]:

        outlier_mask = detect_iqr_outliers(
            trees[col]
        )

        for idx in trees.index[outlier_mask]:

            add_issue(
                issues,
                "警告",
                "IQR_OUTLIER",
                trees.at[idx, "tree_id"],
                col,
                trees.at[idx, col],
                "该数值超出样地数据的IQR统计筛查范围",
                "人工核对，不要直接删除或修改"
            )

    # ======================================
    # 11. 读取人工审核记录
    # ======================================

    if review_file is None:
        reviews = pd.DataFrame(columns=REVIEW_COLUMNS)
    else:
        reviews = pd.read_csv(
            review_file,
            encoding="utf-8-sig",
            dtype=str
        ).fillna("")

    missing_review_columns = [
        col for col in REVIEW_COLUMNS
        if col not in reviews.columns
    ]

    if missing_review_columns:

        raise ValueError(
            f"人工审核文件缺少字段：{missing_review_columns}"
        )

    for col in REVIEW_COLUMNS:
        reviews[col] = (
            reviews[col]
            .astype(str)
            .str.strip()
        )

    review_key_columns = [
        "tree_id",
        "check_field",
        "rule_id"
    ]

    if reviews.duplicated(
        subset=review_key_columns,
        keep=False
    ).any():

        raise ValueError(
            "人工审核记录存在重复匹配键，请检查CSV"
        )

    allowed_statuses = {
        "待审核",
        "已确认正常",
        "已修正"
    }

    invalid_statuses = set(
        reviews["review_status"]
    ) - allowed_statuses - {""}

    if invalid_statuses:

        raise ValueError(
            f"存在不支持的审核状态：{invalid_statuses}"
        )

    # 建立审核记录字典

    review_map = {}

    for _, row in reviews.iterrows():

        key = (
            row["tree_id"],
            row["check_field"],
            row["rule_id"]
        )

        review_map[key] = row.to_dict()

    # ======================================
    # 12. 将审核记录匹配到问题清单
    # ======================================

    issues_df = pd.DataFrame(
        issues,
        columns=ISSUE_COLUMNS
    )

    review_results = []

    current_warning_keys = set()

    for _, issue in issues_df.iterrows():

        if issue["问题等级"] != "警告":

            review_results.append({
                "审核状态": "不适用",
                "审核人员": "",
                "审核日期": "",
                "审核说明": ""
            })

            continue

        key = (
            str(issue["树木编号"]),
            str(issue["检查字段"]),
            str(issue["rule_id"])
        )

        current_warning_keys.add(key)

        record = review_map.get(key)

        if record is None:

            review_results.append({
                "审核状态": "待审核",
                "审核人员": "",
                "审核日期": "",
                "审核说明": ""
            })

        else:

            review_results.append({

                "审核状态": (
                    record["review_status"] or "待审核"
                ),

                "审核人员": record["reviewer"],

                "审核日期": record["review_date"],

                "审核说明": record["review_note"]

            })

    review_result_df = pd.DataFrame(
        review_results,
        columns=REVIEW_RESULT_COLUMNS,
        index=issues_df.index
    )

    issues_df = pd.concat(
        [issues_df, review_result_df],
        axis=1
    )

    # 找出没有匹配到当前问题的审核记录

    unmatched_mask = reviews.apply(
        lambda row: (
            row["tree_id"],
            row["check_field"],
            row["rule_id"]
        ) not in current_warning_keys,
        axis=1
    )

    unmatched_reviews = reviews.loc[
        unmatched_mask
    ].copy()

    # ======================================
    # 13. 统计审核结果
    # ======================================

    blocking_count = int(
        (issues_df["问题等级"] == "阻断").sum()
    )

    warning_df = issues_df[
        issues_df["问题等级"] == "警告"
    ]

    warning_count = len(warning_df)

    pending_count = int(
        (warning_df["审核状态"] == "待审核").sum()
    )

    confirmed_count = int(
        (warning_df["审核状态"] == "已确认正常").sum()
    )

    corrected_count = int(
        (warning_df["审核状态"] == "已修正").sum()
    )

    unmatched_count = len(unmatched_reviews)

    # ======================================
    # 14. 每株树的审核状态
    # ======================================

    def get_tree_status(tree_id):

        records = issues_df[
            issues_df["树木编号"].astype(str)
            == str(tree_id)
        ]

        if (records["问题等级"] == "阻断").any():
            return "不通过"

        warning_records = records[
            records["问题等级"] == "警告"
        ]

        if warning_records.empty:
            return "通过"

        if (warning_records["审核状态"] == "待审核").any():
            return "待复核"

        if (warning_records["审核状态"] == "已修正").any():
            return "待重新验证"

        return "已审核保留"

    trees["validation_status"] = (
        trees["tree_id"].apply(get_tree_status)
    )

    # ======================================
    # 15. 生成检查结论
    # ======================================

    if blocking_count > 0:

        conclusion = "存在阻断问题，暂缓后续计算"

    elif pending_count > 0:

        conclusion = "仍有待审核问题，需要人工复核"

    elif corrected_count > 0:

        conclusion = "存在已修正记录，需要重新运行检查"

    elif unmatched_count > 0:

        conclusion = "存在未匹配的审核记录，需要检查"

    else:

        conclusion = "无阻断问题，警告均已审核，可进入标准匹配与计算准备"

    summary = pd.DataFrame([

        ["输入文件", input_file.name],

        ["人工审核记录文件", review_file.name if review_file else "未提供"],

        ["乔木记录总数", len(trees)],

        ["阻断问题数量", blocking_count],

        ["统计警告总数", warning_count],

        ["待审核警告数量", pending_count],

        ["已确认正常数量", confirmed_count],

        ["已修正待验证数量", corrected_count],

        ["未匹配审核记录数量", unmatched_count],

        ["检查结论", conclusion]

    ], columns=["检查项目", "检查结果"])

    # ======================================
    # 16. 导出审核报告
    # ======================================

    output_file.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with pd.ExcelWriter(
        output_file,
        engine="openpyxl"
    ) as writer:

        summary.to_excel(
            writer,
            sheet_name="Validation_Summary",
            index=False
        )

        issues_df.to_excel(
            writer,
            sheet_name="Validation_Issues",
            index=False
        )

        trees.to_excel(
            writer,
            sheet_name="Trees_Checked",
            index=False
        )

        reviews.to_excel(
            writer,
            sheet_name="Review_Records",
            index=False
        )

        unmatched_reviews.to_excel(
            writer,
            sheet_name="Unmatched_Reviews",
            index=False
        )

    # ======================================
    # 17. 美化Excel报告
    # ======================================

    wb = load_workbook(output_file)

    for ws in wb.worksheets:

        ws.freeze_panes = "A2"

        ws.auto_filter.ref = ws.dimensions

        for cell in ws[1]:

            cell.font = Font(
                bold=True,
                color="FFFFFF"
            )

            cell.fill = PatternFill(
                "solid",
                fgColor="305496"
            )

            cell.alignment = Alignment(
                horizontal="center",
                vertical="center"
            )

        for column_cells in ws.columns:

            max_length = max(
                len(str(cell.value or ""))
                for cell in column_cells
            )

            column_letter = get_column_letter(
                column_cells[0].column
            )

            ws.column_dimensions[
                column_letter
            ].width = min(
                max(max_length + 3, 12),
                42
            )

    wb.save(output_file)

    # ======================================
    # 18. 显示运行结果
    # ======================================

    print("\n========== Data Validator V1.1 ==========")

    print("乔木记录数量：", len(trees))

    print("阻断问题数量：", blocking_count)

    print("统计警告总数：", warning_count)

    print("待审核警告数量：", pending_count)

    print("已确认正常数量：", confirmed_count)

    print("已修正待验证数量：", corrected_count)

    print("未匹配审核记录数量：", unmatched_count)

    print("\n检查结论：", conclusion)

    print("\n报告保存位置：")

    print(output_file)


if __name__ == "__main__":
    main()
