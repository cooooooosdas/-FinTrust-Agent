# 竞赛交付材料生成脚本

本目录是四份必交材料的**可复现构建脚本**。所有脚本均以仓库根目录为基准解析路径，不依赖任何机器绝对路径。

| 脚本 | 产物 | 依赖 |
| --- | --- | --- |
| `build_pdfs.py` | `submission/01_金枢技术设计说明书.pdf`、`submission/04_金枢安全自评报告.pdf` | Python 3.11+、`reportlab` |
| `build_pptx.js` | `submission/02_金枢答辩PPT.pptx` | Node.js 18+、`pptxgenjs` |
| `package_source.py` | `submission/03_金枢完整源代码.zip` | Python 3.11+（标准库） |
| `zip_validation.json` | 上一次源码包打包校验报告 | 由 `package_source.py` 生成 |

## 复现步骤

```bash
# 1) 生成两份 PDF（输出目录可用环境变量覆盖）
pip install reportlab
python submission/tools/build_pdfs.py

# 2) 生成答辩 PPT（截图必须先由真实系统采集，禁止伪造）
cd submission/tools && npm install && node build_pptx.js

# 3) 打包并审计源码包
python submission/tools/package_source.py
```

三个脚本都支持用环境变量重定向输出，便于在不影响正式交付物的情况下做试跑：

- `FINTRUST_PDF_OUT` —— PDF 输出目录
- `FINTRUST_PPT_OUT` —— PPT 输出文件路径
- `FINTRUST_ZIP_OUT` —— 源码 ZIP 输出文件路径

## 素材依赖

`build_pptx.js` 从 `docs/screenshots/` 读取真实系统截图。该目录缺失时脚本会直接报错退出，
**不允许以任何方式伪造或以示意图替代系统截图**。

## 字体

`build_pdfs.py` 优先注册系统微软雅黑（`msyh.ttc` / `msyhbd.ttc`）；在无该字体的系统上自动回退到
ReportLab 内置中文 CID 字体 `STSong-Light`，保证跨平台可运行。
