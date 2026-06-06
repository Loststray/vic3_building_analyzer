# Vic3 Analyzer

这个工具用于分析 Victoria 3 风格的脚本数据，枚举每个建筑可用的生产方式组合，并导出每种组合的投入、产出、劳动力、利润和本地化后的 CSV。

项目目前使用纯 Python 标准库实现，不需要额外安装依赖。

## 输入目录

默认输入目录是当前目录。主流程会先合并以下 4 个文件夹中的所有 `.txt` 文件：

| 源目录 | 合并后的中间文件 | 内容 |
| --- | --- | --- |
| `buildings/` | `buildings.txt` | 建筑对象 |
| `goods/` | `goods.txt` | 商品对象与商品基础价格 |
| `production_methods/` | `pm.txt` | 生产方式对象 |
| `production_methods_groups/` | `pmg.txt` | 生产方式组对象 |

合并顺序按文件名排序，例如 `01_industry.txt`、`02_agro.txt`。合并逻辑复用 [merge_txt.py](merge_txt.py)。

本地化文件放在：

```text
localization/*.yml
```

支持 Victoria 3 常见的本地化格式，例如：

```yml
l_simp_chinese:
 building_food_industry: "食品厂"
 pm_rail_transport_mine: "$pm_rail_transport$"
```

如果 value 恰好是 `$some_key$`，本地化脚本会继续按 `some_key` 链式解析。

## 快速使用

在仓库根目录运行：

```powershell
python Vic3_analyzer\main.py
```

这会依次完成：

1. 合并 4 个输入文件夹，生成 `buildings.txt`、`goods.txt`、`pm.txt`、`pmg.txt`
2. 解析这些中间文件
3. 枚举所有建筑的生产方式组合
4. 生成原始结果 `output.csv`
5. 读取 `localization/*.yml`
6. 生成本地化结果 `output_loc.csv`

成功运行后会看到类似输出：

```text
Parsed 115 buildings, 197 production method groups, and 436 production methods.
Wrote 1638 combinations with 52 item columns to D:\Utils\Vic3_analyzer\output.csv.
Wrote 1639 localized CSV rows to D:\Utils\Vic3_analyzer\output_loc.csv.
```

## 输出文件

### `output.csv`

原始 key 版本，适合继续给程序处理。

表头示例：

```csv
building_group,building,pmg1,pmg2,pmg3,pmg4,goods_input_price,goods_output_prices,profit,profit_per_capita,workforce,grain,groceries,...
```

### `output_loc.csv`

本地化版本，适合直接阅读或放进表格工具中查看。

表头示例：

```csv
建筑组,建筑,生产方式1,生产方式2,生产方式3,生产方式4,商品输入总价格,商品输出总价格,利润,人均利润,劳动力,谷物,加工食品,...
```

## 字段说明

| 字段 | 含义 |
| --- | --- |
| `building_group` | 建筑所属建筑组，来自 building 对象的 `building_group` |
| `building` | 建筑 key |
| `pmg1..pmgN` | 该建筑每个生产方式组中选中的生产方式 |
| `goods_input_price` | 所有投入商品的总价格 |
| `goods_output_prices` | 所有产出商品的总价格 |
| `profit` | 产出价格减投入价格 |
| `profit_per_capita` | `profit / workforce * 52`，输出时保留 2 位小数 |
| `workforce` | `building_modifiers.level_scaled` 中所有 `building_employment_*_add` 的总和 |
| 商品列 | 各商品的净变化量，投入为负，产出为正 |

## 计算规则

### 生产方式组合

每个 building 包含若干 `production_method_groups`。每个 PMG 包含若干可选 `production_methods`。

工具会对每个 building 的 PMG 做笛卡尔积枚举，也就是类似 DFS 的组合：

```text
building
  pmg1: pm_a / pm_b
  pmg2: pm_c / pm_d

组合:
  pm_a + pm_c
  pm_a + pm_d
  pm_b + pm_c
  pm_b + pm_d
```

### 商品数量

对每个 production method，工具读取：

```text
building_modifiers.workforce_scaled.goods_input_*_add
building_modifiers.workforce_scaled.goods_output_*_add
```

规则：

- `goods_input_*_add` 记为负数
- `goods_output_*_add` 记为正数
- `*` 会作为商品名
- 同名商品会累加
- 商品数量支持整数和小数

例如：

```text
goods_input_grain_add = 40
goods_output_groceries_add = 45
```

会输出：

```csv
grain,groceries
-40,45
```

### 劳动力

对每个 production method，工具读取：

```text
building_modifiers.level_scaled.building_employment_*_add
```

所有 `building_employment_*_add` 的整数值会累加到单列：

```csv
workforce
```

不再单独输出 `laborers`、`shopkeepers`、`machinists` 等就业明细列。

### 商品价格与利润

商品价格来自 `goods.txt` 中每个商品对象的：

```text
cost = ...
```

计算公式：

```text
goods_input_price = sum(-amount * cost) for amount < 0
goods_output_prices = sum(amount * cost) for amount > 0
profit = goods_output_prices - goods_input_price
profit_per_capita = profit / workforce * 52
```

如果 `workforce = 0`，`profit_per_capita` 输出为 `0.00`。

## 命令行参数

### 主分析脚本

```powershell
python main.py --help
```

常用参数：

```powershell
python main.py `
  --output output.csv `
  --localized-output output_loc.csv
```

参数说明：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--data-dir` | `main.py` 所在目录 | 包含 4 个输入文件夹和 `localization/` 的目录 |
| `--output` | `<data-dir>/output.csv` | 原始 CSV 输出路径 |
| `--localized-output` | `output_loc.csv` | 本地化 CSV 输出路径 |
| `--missing-pm zero` | `zero` | 缺失 PM 仍保留组合，modifier 视为 0 |
| `--missing-pm skip` |  | 缺失 PM 时跳过该 PM |
| `--strict` | 关闭 | 遇到缺失 PMG 或 PM 时直接失败 |

## Parser 支持的语法

脚本数据不是标准 JSON。内置 parser 支持以下 Victoria/Paradox 风格语法：

- `key = value`
- `{ ... }` 对象或列表
- 裸标识符列表，例如 `{ pm_a pm_b pm_c }`
- 字符串，例如 `"gfx/interface/icon.dds"`
- 整数与浮点数
- `#` 行内注释
- UTF-8 BOM
- 重复 key，重复值会保留并在需要数值时累加

## 主要脚本

| 文件 | 作用 |
| --- | --- |
| [main.py](main.py) | 主流程：合并、解析、枚举组合、计算利润、输出 CSV、本地化 CSV |
| [merge_txt.py](merge_txt.py) | 合并某个目录下的所有 `.txt` 文件 |
| [localization.py](localization.py) | 读取本地化 yml，并替换 CSV 中匹配的 key |

## 注意事项

- `*.txt`、`**/*.txt` 和 `localization/*.yml` 当前在 `.gitignore` 中，适合放置从游戏或 mod 中复制出来的数据文件。
- `output.csv` 和 `output_loc.csv` 是生成物，可以随时重新运行 `main.py` 生成。
- 如果本地化 key 不存在，CSV 中会保留原始 key。
- 如果本地化 value 是 `$key$`，会链式解析；如果是 `扩建$key$` 这类嵌入式文本，目前不会展开。
