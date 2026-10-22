# 0.3.1 部署与局部边界审核复现

2026-10-16。本轮 15 条位点记录、8 次小范围 BLASTn、4 次 DUST 和 1 次 MAFFT 已在本地单线程真实执行完成，不需要启动新的 EDTA、TEtrimmer、RepeatMasker 或全基因组发现任务。以下命令用于上传新版和需要时的服务器独立复现；不会更改旧运行配置、冻结清单、环境中的 editable 安装或旧审核目录。

## 1. 上传与校验

上传 `te-annotation-workflow-v0.3.1.zip` 和同名 `.sha256` 到 `/home/cfy/te_project/`，然后运行：

```bash
bash <<'BASH'
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
cd "$TASK_ROOT"
sha256sum -c te-annotation-workflow-v0.3.1.zip.sha256
test ! -e "$TASK_ROOT/te-annotation-workflow-v0.3.1"
unzip -q te-annotation-workflow-v0.3.1.zip -d "$TASK_ROOT"
"$MICROMAMBA" run -p "$TASK_ROOT/envs/engine" python \
  "$TASK_ROOT/te-annotation-workflow-v0.3.1/scripts/verify_source.py"
echo BOUNDARY_PACKAGE_VERIFIED
BASH
```

若目录已经存在，只运行其中 `verify_source.py` 校验；不要覆盖解压或改写原目录。原有 TE 工作流仍用其原版本和原配置。

## 2. 可选：复现本轮局部比较

这不是必须补跑的失败任务。以下命令只提取 203,158 bp 的有方向序列，包括侧翼；固定 4 组、15 条记录。`H0000060_pair01` 与 `H0000025_native` 几乎重叠，两条记录不能算两个独立位点。全基因组文件仅用于核验 SHA256、提取序列和读取基因注释。

```bash
bash <<'BASH'
set -euo pipefail
TASK_ROOT=/home/cfy/te_project
MICROMAMBA=/home/cfy/minimamba/bin/micromamba
TE_ENV="$TASK_ROOT/envs"
BOUNDARY_REPO="$TASK_ROOT/te-annotation-workflow-v0.3.1"
export PYTHONPATH="$BOUNDARY_REPO/src"
export TEFLOW_REPOSITORY="$BOUNDARY_REPO"
GENOME="$TASK_ROOT/inputs/arabidopsis/TAIR10.fa"
ANNOTATION="$TASK_ROOT/inputs/arabidopsis/Araport11.gtf"
CASE_DIR="$BOUNDARY_REPO/examples/arabidopsis_v022_boundary"
CASE_RUN="$TASK_ROOT/reviews/at_v022_boundary_v031.$(date -u +%Y%m%dT%H%M%SZ).$$"
test ! -e "$CASE_RUN"
mkdir -p "$CASE_RUN"

"$MICROMAMBA" run -p "$TE_ENV/engine" python "$BOUNDARY_REPO/scripts/verify_source.py"
"$MICROMAMBA" run -p "$TE_ENV/engine" python - "$GENOME" "$ANNOTATION" "$CASE_DIR/selection_provenance.json" <<'PY'
import hashlib, json, sys
from pathlib import Path
record=json.loads(Path(sys.argv[3]).read_text())
for path,key in [(sys.argv[1],'genome_sha256'),(sys.argv[2],'annotation_sha256')]:
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    if h.hexdigest()!=record[key]: raise SystemExit('Reference differs: '+path)
    print('VERIFIED',path)
PY

# 复用现有工具；不修改环境。实际版本及执行文件散列进入回执。
"$MICROMAMBA" run -p "$TE_ENV/engine" python - "$MICROMAMBA" "$TE_ENV" "$CASE_RUN/tools.json" <<'PY'
import json,sys
from pathlib import Path
mamba,env,out=sys.argv[1:]
tools={name:{'command':[mamba,'run','-p',str(Path(env)/provider),name],
             'expected_version':None}
       for name,provider in [('blastn','tetrimmer'),('mafft','tetrimmer'),('dustmasker','masking')]}
Path(out).write_text(json.dumps(tools,indent=2)+'\n')
PY

"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow boundary-prepare \
  --genome "$GENOME" --annotation "$ANNOTATION" \
  --loci "$CASE_DIR/at_v022_selected_loci.tsv" \
  --evidence "$CASE_DIR/selection_provenance.json" \
  --tools "$CASE_RUN/tools.json" --output "$CASE_RUN/review" \
  --flank 500 --terminal 100 --msa-group H0000134 --dust-sensitivity

"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow boundary-plan \
  --review "$CASE_RUN/review" --threads 1 > "$CASE_RUN/plan.json"

"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow boundary-run \
  --review "$CASE_RUN/review" --threads 1 --timeout 3600 \
  > "$CASE_RUN/execution.json" 2> "$CASE_RUN/execution.stderr.log"

"$MICROMAMBA" run -p "$TE_ENV/engine" python -m teflow boundary-pack \
  --review "$CASE_RUN/review" --output "$CASE_RUN.feedback.tar.gz"
echo BOUNDARY_REVIEW_COMPLETE
printf 'Feedback: %s\n' "$CASE_RUN.feedback.tar.gz"
BASH
```

若工具探测失败，先查看新目录内 `alignments/*version.log` 与 `failed.json`；不要重复使用同一审核目录启动任务。可选独立依赖配方是 `envs/boundary.yml`，不要求重装工作流全部依赖。本地验证与服务器既有 BLAST 的构建版本不同，服务器复现是独立验证，不承诺逐字相同的 HSP 输出；参数、输入、程序实际版本和文件散列必须一并保留。

## 3. 输出判读

先看 `alignments/complete.json` 的 `self_control_status`，再看 `pair_summary.tsv` 中 `role=candidate, orientation=same, search_mode=dust` 的内部覆盖。`no_dust` 单独比较；反向命中也保留。0 命中与低覆盖只描述当前参数下的报告结果。MAFFT 文件不能直接转成新的 TE 共识库。全部结果保留为待审核证据，不自动导出 GFF、改库、剪除基因或触发全基因组 remasking。
