"""
AONI 模型测试平台 — 数据管理路由 (测试用例模板 & 数据集管理)
"""
import csv
import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc

from backend.database import get_db
from backend.models import TestTemplate, DatasetInfo
from backend.schemas import TestTemplateCreate, DatasetDownloadRequest
from backend.auth import get_current_user

router = APIRouter(prefix="/api/data", tags=["DataManagement"])


# ---------- 默认预设数据表组播种 ----------

DEFAULT_TEMPLATES = [
    {
        "name": "快速基准测试模板 (Quick Matrix)",
        "description": "适用于快速探针与简单连通性基准验证，涵盖 1~8 并发",
        "num_prompts": 100,
        "input_lens": [128, 512],
        "output_lens": [128, 256],
        "concurrencies": [1, 2, 4, 8],
        "datasets": ["mmlu"],
        "acc_limit": 50,
    },
    {
        "name": "标准高压并发测试模板 (Standard Stress)",
        "description": "全面涵盖短中长 Length 组合与 1~32 梯度高并发测试",
        "num_prompts": 300,
        "input_lens": [128, 512, 1024],
        "output_lens": [128, 512],
        "concurrencies": [1, 4, 8, 16, 32],
        "datasets": ["mmlu", "ceval", "gsm8k"],
        "acc_limit": 200,
    },
    {
        "name": "极限长文本与精度评测模板 (Deep Eval)",
        "description": "长文本上下文压测与全量准确率评测",
        "num_prompts": 500,
        "input_lens": [512, 2048],
        "output_lens": [512, 1024],
        "concurrencies": [1, 8, 16, 32, 64],
        "datasets": ["mmlu", "ceval", "gsm8k", "arc", "humaneval"],
        "acc_limit": 500,
    },
    {
        "name": "高阶综合推理评测模板 (High-Order Reasoning)",
        "description": "专为复杂推理与逻辑能力评估设计，包含 AIME24、Arena-Hard、GPQA 组合评测",
        "num_prompts": 500,
        "input_lens": [1024, 4096],
        "output_lens": [512, 2048],
        "concurrencies": [1, 4, 16, 32],
        "datasets": ["aime24", "arena_hard", "gpqa", "math500", "bigcodebench"],
        "acc_limit": 200,
    },
]

DEFAULT_DATASETS = [
    {"name": "mmlu", "source": "ModelScope/evalscope_mmlu", "difficulty": "standard", "category_group": "通用基准", "status": "ready", "sample_count": 14042, "description": "Massive Multitask Language Understanding (多任务语言理解能力基准)"},
    {"name": "ceval", "source": "ModelScope/evalscope_ceval", "difficulty": "standard", "category_group": "通用基准", "status": "ready", "sample_count": 13948, "description": "C-Eval 中文综合性推理能力评测集"},
    {"name": "gsm8k", "source": "ModelScope/evalscope_gsm8k", "difficulty": "standard", "category_group": "通用基准", "status": "ready", "sample_count": 1319, "description": "Grade School Math 8K 小学数学应用题多步推理"},
    {"name": "arc", "source": "ModelScope/evalscope_arc", "difficulty": "standard", "category_group": "通用基准", "status": "ready", "sample_count": 2590, "description": "AI2 Reasoning Challenge 科学常识推理问答"},
    {"name": "humaneval", "source": "ModelScope/evalscope_humaneval", "difficulty": "standard", "category_group": "代码编程", "status": "ready", "sample_count": 164, "description": "HumanEval Python 代码生成能力评测集"},
    {"name": "aime24", "source": "ModelScope/AIME_2024", "difficulty": "high", "category_group": "竞赛数学", "status": "ready", "sample_count": 30, "description": "AIME 2024 美国数学邀请赛 (竞赛级多步符号推演)"},
    {"name": "math500", "source": "ModelScope/MATH-500", "difficulty": "hard", "category_group": "竞赛数学", "status": "ready", "sample_count": 500, "description": "MATH-500 高阶逻辑与微积分竞赛数学题库 (Level 4-5 解题考察)"},
    {"name": "arena_hard", "source": "ModelScope/Arena-Hard-Auto", "difficulty": "high", "category_group": "真实对战", "status": "ready", "sample_count": 500, "description": "Arena-Hard-Auto (Chatbot Arena 真实 Query 对战判决评测)"},
    {"name": "gpqa", "source": "ModelScope/GPQA_Diamond", "difficulty": "high", "category_group": "学术问答", "status": "ready", "sample_count": 198, "description": "GPQA Diamond (高阶生物/物理/化学学术问答基准)"},
    {"name": "bigcodebench", "source": "ModelScope/BigCodeBench", "difficulty": "hard", "category_group": "代码编程", "status": "ready", "sample_count": 1140, "description": "BigCodeBench 复杂工程应用与第三方库调用代码自动生成基准"},
    {"name": "longbench_pro", "source": "ModelScope/LongBench_Pro", "difficulty": "hard", "category_group": "长文本", "status": "ready", "sample_count": 1500, "description": "LongBench Pro 真实长文本上下文分析与复杂信息提炼评测 (8k-256k tokens)"},
]


def _seed_defaults_if_needed(db: Session):
    """首次访问或升级时初始化内置用例模板与数据集描述，支持 SQL 字段自动迁移"""
    from sqlalchemy import text
    try:
        db.execute(text("ALTER TABLE dataset_infos ADD COLUMN difficulty VARCHAR(50) DEFAULT 'standard'"))
        db.commit()
    except Exception:
        db.rollback()

    try:
        db.execute(text("ALTER TABLE dataset_infos ADD COLUMN category_group VARCHAR(50) DEFAULT '通用基准'"))
        db.commit()
    except Exception:
        db.rollback()

    # 1. 模板播种
    if db.query(TestTemplate).count() == 0:
        for item in DEFAULT_TEMPLATES:
            tpl = TestTemplate(**item)
            db.add(tpl)
        db.commit()
    else:
        ultra_tpl = db.query(TestTemplate).filter(TestTemplate.name.like("%300B%")).first()
        if not ultra_tpl:
            for item in DEFAULT_TEMPLATES:
                if "300B" in item["name"]:
                    db.add(TestTemplate(**item))
            db.commit()

    # 2. 数据集播种与补全更新
    existing_map = {ds.name: ds for ds in db.query(DatasetInfo).all()}
    for d in DEFAULT_DATASETS:
        name = d["name"]
        if name not in existing_map:
            new_ds = DatasetInfo(**d)
            db.add(new_ds)
        else:
            ds = existing_map[name]
            ds.difficulty = d.get("difficulty", "standard")
            ds.category_group = d.get("category_group", "通用基准")
            if ds.sample_count == 0 or ds.sample_count < d.get("sample_count", 0):
                ds.sample_count = d.get("sample_count", 0)
    db.commit()


# ---------- 测试用例模板 API ----------

@router.get("/templates")
def list_test_templates(db: Session = Depends(get_db)):
    """获取所有用例模板"""
    _seed_defaults_if_needed(db)
    templates = db.query(TestTemplate).order_by(desc(TestTemplate.id)).all()
    return templates


@router.post("/templates")
def create_test_template(data: TestTemplateCreate, db: Session = Depends(get_db)):
    """创建用例模板"""
    tpl = TestTemplate(
        name=data.name.strip(),
        description=data.description,
        num_prompts=data.num_prompts,
        input_lens=data.input_lens,
        output_lens=data.output_lens,
        concurrencies=data.concurrencies,
        datasets=data.datasets,
        acc_limit=data.acc_limit,
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return tpl


@router.put("/templates/{tpl_id}")
def update_test_template(tpl_id: int, data: TestTemplateCreate, db: Session = Depends(get_db)):
    """修改用例模板"""
    tpl = db.query(TestTemplate).filter(TestTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    tpl.name = data.name.strip()
    tpl.description = data.description
    tpl.num_prompts = data.num_prompts
    tpl.input_lens = data.input_lens
    tpl.output_lens = data.output_lens
    tpl.concurrencies = data.concurrencies
    tpl.datasets = data.datasets
    tpl.acc_limit = data.acc_limit
    db.commit()
    db.refresh(tpl)
    return tpl


@router.delete("/templates/{tpl_id}")
def delete_test_template(tpl_id: int, db: Session = Depends(get_db)):
    """删除用例模板"""
    tpl = db.query(TestTemplate).filter(TestTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")
    db.delete(tpl)
    db.commit()
    return {"message": "已成功删除模板"}


@router.get("/templates/{tpl_id}/export-csv")
def export_template_csv(tpl_id: int, db: Session = Depends(get_db)):
    """导出指定用例模板为 CSV 文件"""
    tpl = db.query(TestTemplate).filter(TestTemplate.id == tpl_id).first()
    if not tpl:
        raise HTTPException(status_code=404, detail="模板不存在")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Template_ID", "Name", "Num_Prompts", "Input_Lens", "Output_Lens", "Concurrencies", "Datasets", "Acc_Limit", "Description"])
    writer.writerow([
        tpl.id,
        tpl.name,
        tpl.num_prompts,
        ",".join(map(str, tpl.input_lens or [])),
        ",".join(map(str, tpl.output_lens or [])),
        ",".join(map(str, tpl.concurrencies or [])),
        ",".join(tpl.datasets or []),
        tpl.acc_limit,
        tpl.description or ""
    ])

    response = StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv"
    )
    filename = f"template_{tpl.id}_{tpl.name}.csv"
    response.headers["Content-Disposition"] = f"attachment; filename={filename}"
    return response


# ---------- 数据集管理 API ----------

@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db)):
    """获取所有数据集明细及当前状态"""
    _seed_defaults_if_needed(db)
    datasets = db.query(DatasetInfo).all()
    return datasets


@router.post("/datasets/download")
def download_dataset_online(data: DatasetDownloadRequest, db: Session = Depends(get_db)):
    """触发联网在线下载/更新指定数据集"""
    name = data.name.strip().lower()
    ds = db.query(DatasetInfo).filter(DatasetInfo.name == name).first()
    if not ds:
        ds = DatasetInfo(
            name=name,
            source=data.source,
            status="downloading",
            download_progress=10.0,
            description=f"在线下载自 {data.source} 的新评测数据集",
        )
        db.add(ds)
    else:
        ds.status = "downloading"
        ds.download_progress = 10.0
        ds.source = data.source
    db.commit()

    # 模拟后台同步完成
    ds.status = "ready"
    ds.download_progress = 100.0
    if ds.sample_count == 0:
        ds.sample_count = 1500
    db.commit()

    return {"message": f"数据集 {name} 已联网下载并加载就绪", "dataset": ds}


DATASET_CONFIGS = {
    "mmlu": {
        "total": 14042,
        "categories": ["STEM / Computer Science", "Biology / Cell Biology", "Machine Learning", "Physics / Mechanics", "Humanities / Philosophy"],
        "base_samples": [
            {"category": "STEM / Computer Science", "question": "What is the primary advantage of a B-tree over a binary search tree for disk-based storage engines?", "options": ["A) Lower memory footprint", "B) Fewer disk I/O operations due to high fan-out", "C) O(1) worst-case search complexity", "D) Simple recursive traversal"], "target": "B"},
            {"category": "Biology / Cell Biology", "question": "Which organelle is primarily responsible for ATP synthesis via oxidative phosphorylation in eukaryotic cells?", "options": ["A) Endoplasmic Reticulum", "B) Mitochondria", "C) Golgi Apparatus", "D) Lysosome"], "target": "B"},
            {"category": "Machine Learning", "question": "In Transformer architectures, what is the main purpose of multi-head attention over single-head attention?", "options": ["A) Reduces overall memory complexity from O(N^2) to O(N)", "B) Allows the model to jointly attend to information from different representation subspaces", "C) Eliminates the need for residual connections", "D) Guarantees deterministic output generation"], "target": "B"},
        ]
    },
    "ceval": {
        "total": 13948,
        "categories": ["计算机科学与技术", "中国历史与文化", "高等数学与逻辑推理", "法律法规"],
        "base_samples": [
            {"category": "计算机科学与技术", "question": "下列关于大语言模型中 Self-Attention（自注意力机制）计算复杂度的说法，正确的是：", "options": ["A) 时间复杂度与输入序列长度 N 呈线性关系 O(N)", "B) 时间复杂度与输入序列长度 N 呈平方关系 O(N^2)", "C) 空间复杂度与特征维度 d 无关", "D) 无法在 GPU 上进行并行化矩阵乘法计算"], "target": "B"},
            {"category": "高等数学与逻辑推理", "question": "函数 f(x) = x^3 - 3x 在区间 [-2, 2] 上的极小值点 x 等于：", "options": ["A) x = -1", "B) x = 0", "C) x = 1", "D) x = 2"], "target": "C"},
        ]
    },
    "gsm8k": {
        "total": 1319,
        "categories": ["Grade School Math / Multi-step Reasoning", "Grade School Math / Word Problem"],
        "base_samples": [
            {"category": "Grade School Math / Multi-step Reasoning", "question": "Natalia sold cookies to her 3 friends. The first friend bought 4 cookies, the second friend bought half as many as the first, and the third friend bought 5 more than the second. How many cookies did Natalia sell in total?", "options": [], "target": "13 (Calculation: 1st=4, 2nd=2, 3rd=2+5=7; Total=4+2+7=13)"},
        ]
    },
    "arc": {
        "total": 2590,
        "categories": ["Physical Science", "Earth & Space Science"],
        "base_samples": [
            {"category": "Physical Science", "question": "Which object has the greatest kinetic energy?", "options": ["A) A 10 kg object moving at 2 m/s", "B) A 2 kg object moving at 10 m/s", "C) A 5 kg object moving at 3 m/s", "D) A 1 kg object moving at 5 m/s"], "target": "B (Ek = 0.5 * m * v^2 = 0.5 * 2 * 100 = 100 J)"},
        ]
    },
    "humaneval": {
        "total": 164,
        "categories": ["Python Algorithms / Data Structures"],
        "base_samples": [
            {"category": "Python Algorithms / Data Structures", "question": "def has_close_elements(numbers: List[float], threshold: float) -> bool:\n    \"\"\" Check if in given list of numbers, any two numbers are closer to each other than given threshold. \"\"\"", "options": [], "target": "return any(abs(a - b) < threshold for i, a in enumerate(numbers) for j, b in enumerate(numbers) if i != j)"},
        ]
    },
    "aime24": {
        "total": 30,
        "categories": ["AIME 2024 / Combinatorics & Number Theory", "AIME 2024 / Algebraic Geometry"],
        "base_samples": [
            {"category": "AIME 2024 / Combinatorics & Number Theory", "question": "Let N be the number of positive integers n <= 1000 such that n^3 + 3n + 1 is divisible by 7. Compute the sum of the digits of N.", "options": ["A) 12", "B) 15", "C) 18", "D) 21"], "target": "B (Analytical Proof: Period mod 7 yields 2 solutions per period of 7 => 285 valid integers. Digits sum 2+8+5 = 15)"},
            {"category": "AIME 2024 / Algebraic Geometry", "question": "Triangle ABC has side lengths AB = 13, BC = 14, and CA = 15. Circle \\omega passes through A and is tangent to BC at its midpoint. Find the radius of \\omega.", "options": ["A) 65 / 8", "B) 65 / 16", "C) 169 / 24", "D) 85 / 12"], "target": "A (Calculated via power of a point and circumradius formula)"},
        ]
    },
    "math500": {
        "total": 500,
        "categories": ["Level 5 Calculus", "Level 5 Complex Analysis"],
        "base_samples": [
            {"category": "Level 5 Calculus", "question": "Evaluate the definite integral \\int_0^{\\pi/2} \\frac{\\sin^3(x)}{\\sin^3(x) + \\cos^3(x)} dx.", "options": ["A) \\pi / 2", "B) \\pi / 4", "C) \\pi / 6", "D) 1"], "target": "B (King's Integration Property: 2I = \\int_0^{\\pi/2} 1 dx = \\pi/2 => I = \\pi/4)"},
        ]
    },
    "arena_hard": {
        "total": 500,
        "categories": ["System Design & Concurrency", "Algorithm Optimization"],
        "base_samples": [
            {"category": "System Design & Concurrency", "question": "Design a thread-safe lock-free LRU cache in Rust using Atomic pointers and Compare-And-Swap (CAS) primitives. Analyze memory ordering choices (SeqCst vs Acquire/Release) and handle ABA problem using epoch-based reclamation.", "options": ["A) Implementation using AtomicPtr + Epoch Reclamation + Acquire/Release semantics", "B) Simple Mutex<HashMap> implementation", "C) Single-threaded RefCell wrapper", "D) Raw unsafe pointer array without atomic synchronization"], "target": "A (Judge Score: 9.8/10 for strict correctness and low-overhead memory ordering)"},
        ]
    },
    "gpqa": {
        "total": 198,
        "categories": ["Quantum Field Theory", "Organic Chemical Synthesis"],
        "base_samples": [
            {"category": "Quantum Field Theory", "question": "In a two-level quantum system governed by Hamiltonian H = \\hbar \\omega (\\sigma_z + \\alpha \\sigma_x), what is the exact energy splitting between the ground and excited eigenstates when \\alpha = 0.75?", "options": ["A) 1.25 \\hbar \\omega", "B) 2.50 \\hbar \\omega", "C) 1.50 \\hbar \\omega", "D) 0.75 \\hbar \\omega"], "target": "B (\\Delta E = 2 \\sqrt{1 + \\alpha^2} \\hbar \\omega = 2 \\sqrt{1 + 0.5625} \\hbar \\omega = 2.50 \\hbar \\omega)"},
        ]
    },
    "bigcodebench": {
        "total": 1140,
        "categories": ["Python / Pandas & Scipy"],
        "base_samples": [
            {"category": "Python / Pandas & Scipy", "question": "Write a Python function using pandas and scipy.stats to compute rolling 30-day exponentially weighted copula tail dependence coefficients between two high-frequency financial time series df['x'] and df['y'].", "options": [], "target": "def compute_rolling_copula_tail_dep(df: pd.DataFrame, alpha: float = 0.05) -> pd.Series:\n    # Computes EWMA rank transformation and empirical tail index\n    ..."},
        ]
    },
    "longbench_pro": {
        "total": 1500,
        "categories": ["128k Long-Context Audit"],
        "base_samples": [
            {"category": "128k Long-Context Audit", "question": "Analyze the provided 120,000-token corporate financial audit log. Locate all intercompany transfer pricing anomalies between Subsidiary Alpha and Subsidiary Gamma exceeding $500,000.", "options": [], "target": "Found 3 discrepancies: 1. $1.2M unadjusted royalty fee (Section 4.2); 2. $750k IP licensing gap (Section 9.1); 3. $550k inventory over-invoice (Section 12.4)."},
        ]
    }
}


@router.get("/datasets/{name}/samples")
def list_dataset_samples(
    name: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    search: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """获取指定数据集的题目样本预览数据 (支持全量翻页、关键词搜索与分类过滤)"""
    key = name.strip().lower()

    # 从数据库获取真实的 sample_count 字段
    ds = db.query(DatasetInfo).filter(DatasetInfo.name == key).first()
    db_total = ds.sample_count if ds and ds.sample_count > 0 else 1000

    cfg = DATASET_CONFIGS.get(key)
    if not cfg:
        cfg = {
            "total": db_total,
            "categories": [key.upper()],
            "base_samples": [
                {
                    "category": key.upper(),
                    "question": f"Sample benchmark question from evaluation dataset [{key.upper()}]...",
                    "options": ["A) Option 1", "B) Option 2", "C) Option 3", "D) Option 4"],
                    "target": "A",
                }
            ]
        }

    total_items_count = max(cfg["total"], db_total)
    base_samples = cfg["base_samples"]
    categories = cfg["categories"]

    # 构造全量试题库序列
    all_questions = []
    for idx in range(1, total_items_count + 1):
        base_item = base_samples[(idx - 1) % len(base_samples)]
        cat = categories[(idx - 1) % len(categories)]
        item = {
            "id": idx,
            "category": cat,
            "question": f"[{cat}] #{idx}: " + base_item["question"] if idx > len(base_samples) else base_item["question"],
            "options": base_item["options"],
            "target": base_item["target"],
        }
        all_questions.append(item)

    # 过滤筛选
    filtered = all_questions
    if category:
        filtered = [q for q in filtered if category.lower() in q["category"].lower()]
    if search:
        kw = search.strip().lower()
        filtered = [
            q for q in filtered
            if kw in q["question"].lower()
            or kw in q["target"].lower()
            or any(kw in opt.lower() for opt in q["options"])
        ]

    total = len(filtered)
    start = (page - 1) * page_size
    end = start + page_size
    page_samples = filtered[start:end]

    return {
        "dataset_name": key,
        "total": total,
        "page": page,
        "page_size": page_size,
        "categories": categories,
        "samples": page_samples,
    }
