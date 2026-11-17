
from pathlib import Path
import argparse
import math
import pandas as pd

from standard_pdf import load_tables


# ============================================================
# 1. 项目路径与规则文件
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RULES_DIR = PROJECT_ROOT / "data" / "rules"

BIOMASS_FILE = RULES_DIR / "biomass_rules.csv"
SPECIES_FILE = RULES_DIR / "species_mapping.csv"
CARBON_FILE = RULES_DIR / "carbon_fractions.csv"
STANDARD_PDF = PROJECT_ROOT / "docs" / "standards" / "GBT+43648-2024 生物量标准.pdf"


# ============================================================
# 2. 自定义异常
# ============================================================

class RuleEngineError(Exception):
    """规则引擎基础异常。"""


class RuleNotFoundError(RuleEngineError):
    """没有找到对应的国标计算规则。"""


class HeightRequiredError(RuleEngineError):
    """二元模型缺少树高。"""


class InvalidMeasurementError(RuleEngineError):
    """胸径或树高数据不合法。"""


class UnapprovedSpeciesError(RuleEngineError):
    """树种未通过人工匹配审核。"""


class UnsupportedModelError(RuleEngineError):
    """该树种不支持所选模型。"""


class AmbiguousSpeciesError(RuleEngineError):
    """树种名称对应多个国标匹配结果。"""


# ============================================================
# 3. 基础工具函数
# ============================================================

def clean_text(value):
    """统一处理文本和空值。"""
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def to_positive_number(value, field_name):
    """将测量值转换为合法的正数。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise InvalidMeasurementError(
            f"{field_name}必须是有效数字，当前值：{value}"
        )

    if not math.isfinite(number) or number <= 0:
        raise InvalidMeasurementError(
            f"{field_name}必须是有限正数，当前值：{value}"
        )

    return number


# ============================================================
# 4. 国家标准规则引擎
# ============================================================

class StandardRuleEngine:

    def __init__(self, *, province=None):
        self.province = clean_text(province).removesuffix("省").removesuffix("市")

        self.biomass_rules = self._load_csv(BIOMASS_FILE)
        self.species_mapping = self._load_csv(SPECIES_FILE)
        self.carbon_fractions = self._load_csv(CARBON_FILE)

        self._check_columns()

    def _load_csv(self, file_path):

        if not file_path.exists():
            raise FileNotFoundError(
                f"规则文件不存在：{file_path}"
            )

        return pd.read_csv(
            file_path,
            encoding="utf-8-sig"
        )

    def _check_columns(self):

        required = {
            "biomass_rules": [
                "rule_id",
                "standard_id",
                "species_group",
                "population_scope",
                "model_type",
                "dbh_class",
                "a0",
                "a1",
                "a2",
                "formula",
                "source_table",
                "source_page",
                "rule_status"
            ],
            "species_mapping": [
                "input_name",
                "normalized_name",
                "scientific_name",
                "standard_species_group",
                "population_scope",
                "mapping_status"
            ],
            "carbon_fractions": [
                "species_group",
                "population_scope",
                "component",
                "cf_value",
                "status"
            ]
        }

        datasets = {
            "biomass_rules": self.biomass_rules,
            "species_mapping": self.species_mapping,
            "carbon_fractions": self.carbon_fractions
        }

        for name, columns in required.items():

            missing = set(columns) - set(datasets[name].columns)

            if missing:
                raise RuleEngineError(
                    f"{name}缺少必要字段：{sorted(missing)}"
                )

    # --------------------------------------------------------
    # 4.1 树种匹配
    # --------------------------------------------------------

    def match_species(self, species_name):

        name = clean_text(species_name)

        if not name:
            raise UnapprovedSpeciesError("树种名称为空。")

        mapping = self.species_mapping

        candidate_columns = [
            "input_name",
            "normalized_name",
            "scientific_name"
        ]

        matched = pd.Series(False, index=mapping.index)

        for column in candidate_columns:

            matched |= mapping[column].apply(
                lambda x: clean_text(x).casefold()
                == name.casefold()
            )

        candidates = mapping.loc[matched]

        if candidates.empty:
            raise UnapprovedSpeciesError(
                f"未找到树种“{name}”的国标匹配记录。"
            )

        # 不允许一个名称对应多个不同的国标树种组
        unique_groups = candidates[
            ["standard_species_group", "population_scope"]
        ].drop_duplicates()

        if len(unique_groups) != 1:
            raise AmbiguousSpeciesError(
                f"树种“{name}”存在多个匹配结果，需要人工确认。"
            )

        approved = candidates[
            candidates["mapping_status"]
            .astype(str).str.strip().str.lower()
            == "approved"
        ]

        if approved.empty:
            raise UnapprovedSpeciesError(
                f"树种“{name}”尚未通过人工审核。"
            )

        return approved.iloc[0]

    def _lookup_pdf(self, name, model_type, dbh):
        try:
            regions, models, carbon, annex, aliases = load_tables(
                str(STANDARD_PDF), STANDARD_PDF.stat().st_mtime_ns
            )
        except FileNotFoundError as error:
            raise RuleNotFoundError(f"未找到本机国标 PDF：{STANDARD_PDF}") from error
        except ImportError as error:
            raise RuleEngineError("国标 PDF 查询需要安装 PyMuPDF。") from error
        except (RuntimeError, ValueError, OSError) as error:
            raise RuleEngineError(f"无法读取国标模型表：{error}") from error

        dbh_class = "ge_5" if dbh >= 5 else "lt_5"
        group = aliases.get(name, name)
        if group in annex:
            if model_type != "one_variable":
                raise UnsupportedModelError(f"{name}在表E.1中仅提供一元模型。")
            a0, a1, _, _, cf = annex[group]
            scope, a2, page, cf_page, table, cf_table = "全国", None, 235, 235, "表E.1", "表E.1"
            rule_id = f"GBT43648-E.1-{group}"
        else:
            candidates = [(number, scope) for number, (species, _, scope) in regions.items()
                          if species == group]
            matches = [(number, scope) for number, scope in candidates
                       if scope.startswith("全国") or self._explicit_province(scope)]
            if not candidates:
                raise RuleNotFoundError(f"国标表1和表E.1未找到“{name}”的明确匹配。")
            if len(matches) != 1:
                scopes = "；".join(scope for _, scope in candidates)
                raise AmbiguousSpeciesError(f"{name}需确认表1的适用总体：{scopes}")
            number, scope = matches[0]
            table_number = 2 if dbh >= 5 else 3
            table = f"表{table_number}"
            _, _, parameters, page = models[table_number, number]
            if model_type == "one_variable":
                a0, a1 = parameters[:2]
                a2 = None
            else:
                a0, a1, a2 = parameters[2:]
            cf, cf_page = carbon[group]
            cf_table = "表14"
            rule_id = f"GBT43648-{table_number}-{number}-{model_type}"

        rule = {
            "dbh_class": dbh_class, "a0": a0, "a1": a1, "a2": a2,
            "formula": "MA=a0*D^a1" if a2 is None else "MA=a0*D^a1*H^a2",
            "rule_id": rule_id, "standard_id": "GB/T 43648-2024",
            "source_table": table, "source_page": page,
        }
        return group, scope, rule, {
            "cf_value": cf, "source_table": cf_table, "source_page": cf_page
        }

    def _explicit_province(self, scope):
        # 只自动选择无地区、起源或例外附加条件的明确省级列表。
        if not self.province:
            return False
        import re
        return bool(re.fullmatch(r"[一-鿿]{2,3}(?:、[一-鿿]{2,3})*", scope)
                    and self.province in scope.split("、"))

    # --------------------------------------------------------
    # 4.2 根据模型和胸径匹配生物量参数
    # --------------------------------------------------------

    def get_biomass_rule(
        self,
        species_group,
        population_scope,
        model_type,
        dbh_cm
    ):

        dbh_class = "lt_5" if dbh_cm < 5.0 else "ge_5"

        rules = self.biomass_rules

        matched = rules[
            (rules["species_group"] == species_group)
            & (rules["population_scope"] == population_scope)
            & (rules["model_type"] == model_type)
            & (rules["dbh_class"] == dbh_class)
        ]

        if matched.empty:

            # 判断是否存在该树种的其他模型
            species_rules = rules[
                (rules["species_group"] == species_group)
                & (rules["population_scope"] == population_scope)
            ]

            if not species_rules.empty:
                raise UnsupportedModelError(
                    f"{species_group}没有可用的{model_type}模型，"
                    "不允许自动切换其他模型。"
                )

            raise RuleNotFoundError(
                f"没有找到对应参数：{species_group}、"
                f"{model_type}、{dbh_class}"
            )

        official = matched[
            matched["rule_status"]
            .astype(str).str.strip().str.lower()
            == "official"
        ]

        if len(official) != 1:
            raise RuleEngineError(
                f"规则匹配数量异常：{len(official)}，"
                "请检查规则库是否存在重复或未审核参数。"
            )

        return official.iloc[0]

    # --------------------------------------------------------
    # 4.3 匹配地上含碳系数
    # --------------------------------------------------------

    def get_carbon_fraction(
        self,
        species_group,
        population_scope
    ):

        fractions = self.carbon_fractions

        matched = fractions[
            (fractions["species_group"] == species_group)
            & (fractions["population_scope"] == population_scope)
            & (fractions["component"] == "aboveground")
            & (
                fractions["status"]
                .astype(str).str.strip().str.lower()
                == "official"
            )
        ]

        if len(matched) != 1:
            raise RuleNotFoundError(
                f"{species_group}没有唯一有效的地上含碳系数。"
            )

        cf = float(matched.iloc[0]["cf_value"])

        if not math.isfinite(cf) or not 0 < cf <= 1:
            raise RuleEngineError(
                f"含碳系数不合法：{cf}"
            )

        return matched.iloc[0]

    # --------------------------------------------------------
    # 4.4 单株生物量和碳储量计算
    # --------------------------------------------------------

    def calculate_tree(
        self,
        species_name,
        dbh_cm,
        height_m=None,
        model_type="two_variable",
        tree_id=None
    ):

        model_type = clean_text(model_type).lower()

        if model_type not in [
            "one_variable",
            "two_variable"
        ]:
            raise UnsupportedModelError(
                f"不支持的模型类型：{model_type}"
            )

        # 1. 测量数据检查
        dbh = to_positive_number(dbh_cm, "胸径")

        height = None

        if model_type == "two_variable":

            if height_m is None or clean_text(height_m) == "":
                raise HeightRequiredError(
                    "二元模型必须提供树高。"
                )

            height = to_positive_number(height_m, "树高")

        name = clean_text(species_name)
        # 仅在规则库没有该名称时查 PDF，保留已录入的匹配和审核状态。
        mapping_columns = self.species_mapping[
            ["input_name", "normalized_name", "scientific_name"]
        ]
        known = name and any(
            mapping_columns[column].map(lambda value: clean_text(value).casefold())
            .eq(name.casefold()).any()
            for column in mapping_columns
        )
        if known or not name:
            mapping = self.match_species(name)
            species_group = clean_text(mapping["standard_species_group"])
            population_scope = clean_text(mapping["population_scope"])
            rule = self.get_biomass_rule(species_group, population_scope, model_type, dbh)
            carbon_rule = self.get_carbon_fraction(species_group, population_scope)
        else:
            species_group, population_scope, rule, carbon_rule = self._lookup_pdf(
                name, model_type, dbh
            )

        a0 = float(rule["a0"])
        a1 = float(rule["a1"])

        if not math.isfinite(a0) or a0 <= 0:
            raise RuleEngineError("模型参数a0不合法。")

        if not math.isfinite(a1):
            raise RuleEngineError("模型参数a1不合法。")

        # 4. 计算地上生物量
        if model_type == "one_variable":

            agb = a0 * (dbh ** a1)

        else:

            a2 = float(rule["a2"])

            if not math.isfinite(a2):
                raise RuleEngineError(
                    "二元模型缺少有效的a2参数。"
                )

            agb = (
                a0
                * (dbh ** a1)
                * (height ** a2)
            )

        if not math.isfinite(agb) or agb <= 0:
            raise RuleEngineError(
                "生物量计算结果异常。"
            )

        cf = float(carbon_rule["cf_value"])
        if not math.isfinite(cf) or not 0 < cf <= 1:
            raise RuleEngineError(f"含碳系数不合法：{cf}")

        # 6. 计算地上碳储量
        agc = agb * cf

        # 7. 生成可追溯结果
        return {

            "tree_id": clean_text(tree_id),

            "original_species": clean_text(species_name),

            "standard_species_group": species_group,

            "population_scope": population_scope,

            "dbh_cm": dbh,

            "height_m": height,

            "model_type": model_type,

            "dbh_class": clean_text(rule["dbh_class"]),

            "a0": a0,

            "a1": a1,

            "a2": (
                float(rule["a2"])
                if model_type == "two_variable"
                else None
            ),

            "AGB_kg": agb,

            "CF": cf,

            "AGC_kgC": agc,

            "formula": clean_text(rule["formula"]),

            "rule_id": clean_text(rule["rule_id"]),

            "standard_id": clean_text(rule["standard_id"]),

            "source_table": clean_text(rule["source_table"]),

            "source_page": clean_text(rule["source_page"]),

            "carbon_source_table": clean_text(
                carbon_rule["source_table"]
            ),

            "carbon_source_page": clean_text(
                carbon_rule["source_page"]
            ),

            "calculation_status": "success",

            "error_message": ""
        }

    # --------------------------------------------------------
    # 4.5 批量计算
    # --------------------------------------------------------

    def calculate_records(
        self,
        records,
        model_type="two_variable"
    ):

        if isinstance(records, pd.DataFrame):
            records = records.to_dict(orient="records")

        results = []

        for record in records:

            try:

                result = self.calculate_tree(
                    species_name=record.get("species"),
                    dbh_cm=record.get("dbh_cm"),
                    height_m=record.get("height_m"),
                    model_type=model_type,
                    tree_id=record.get("tree_id")
                )

            except RuleEngineError as exc:

                result = {
                    "tree_id": clean_text(
                        record.get("tree_id")
                    ),
                    "original_species": clean_text(
                        record.get("species")
                    ),
                    "calculation_status": "blocked",
                    "error_message": str(exc)
                }

            results.append(result)

        return pd.DataFrame(results)


# ============================================================
# 5. 自检功能
# ============================================================

def run_self_test():

    engine = StandardRuleEngine()

    test_cases = [

        {
            "name": "柳杉一元模型 D=10",
            "args": {
                "species_name": "柳杉",
                "dbh_cm": 10,
                "model_type": "one_variable"
            },
            "expected_agb": 22.9538275123
        },

        {
            "name": "柳杉二元模型 D=10 H=8",
            "args": {
                "species_name": "柳杉",
                "dbh_cm": 10,
                "height_m": 8,
                "model_type": "two_variable"
            },
            "expected_agb": 21.3159276773
        },

        {
            "name": "柳杉一元模型 D=4.99",
            "args": {
                "species_name": "柳杉",
                "dbh_cm": 4.99,
                "model_type": "one_variable"
            },
            "expected_agb": 5.0774819451
        },

        {
            "name": "柳杉二元模型 D=4.99 H=3.2",
            "args": {
                "species_name": "柳杉",
                "dbh_cm": 4.99,
                "height_m": 3.2,
                "model_type": "two_variable"
            },
            "expected_agb": 3.4727148780
        }
    ]

    print("\n========== Standard Rule Engine V1.0 ==========\n")

    passed = 0

    for case in test_cases:

        result = engine.calculate_tree(**case["args"])

        actual = result["AGB_kg"]

        expected = case["expected_agb"]

        success = math.isclose(
            actual,
            expected,
            rel_tol=1e-9,
            abs_tol=1e-9
        )

        if success:
            passed += 1

        print(
            f"{'通过' if success else '失败'} | "
            f"{case['name']}"
        )

        print(f"  计算值：{actual:.10f} kg")
        print(f"  参考值：{expected:.10f} kg")
        print(f"  AGC：{result['AGC_kgC']:.10f} kg C")

    # 检查D=5.0的区间边界
    boundary = engine.calculate_tree(
        species_name="柳杉",
        dbh_cm=5.0,
        model_type="one_variable"
    )

    boundary_ok = boundary["dbh_class"] == "ge_5"

    if boundary_ok:
        passed += 1

    print(
        f"\n{'通过' if boundary_ok else '失败'} | "
        "D=5.0cm边界判断"
    )

    # 检查二元模型缺少树高时是否阻断
    try:

        engine.calculate_tree(
            species_name="柳杉",
            dbh_cm=10,
            height_m=None,
            model_type="two_variable"
        )

        print("失败 | 二元模型缺少树高检查")

    except HeightRequiredError:

        passed += 1
        print("通过 | 二元模型缺少树高检查")

    print("\n--------------------------------")
    print(f"自检通过：{passed}/6")
    print("--------------------------------")

    if passed != 6:
        raise SystemExit("规则引擎自检未全部通过。")

    print("\nStandard Rule Engine V1.0 自检成功！")


# ============================================================
# 6. 程序入口
# ============================================================

if __name__ == "__main__":

    parser = argparse.ArgumentParser(
        description="GB/T 43648-2024 生物量规则引擎"
    )

    parser.add_argument(
        "--self-test",
        action="store_true",
        help="运行规则引擎自检"
    )

    args = parser.parse_args()

    if args.self_test:
        run_self_test()

    else:
        print("Standard Rule Engine V1.0")
        print("运行自检：python src/standard_rule_engine.py --self-test")
