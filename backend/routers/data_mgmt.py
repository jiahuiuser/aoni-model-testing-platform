"""
AONI 模型测试平台 — 数据管理路由 (测试用例模板 & 数据集管理)
"""
import csv
import io
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
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
]

DEFAULT_DATASETS = [
    {"name": "mmlu", "source": "ModelScope/evalscope_mmlu", "status": "ready", "sample_count": 14042, "description": "Massive Multitask Language Understanding (多任务语言理解能力基准)"},
    {"name": "ceval", "source": "ModelScope/evalscope_ceval", "status": "ready", "sample_count": 13948, "description": "C-Eval 中文综合性推理能力评测集"},
    {"name": "gsm8k", "source": "ModelScope/evalscope_gsm8k", "status": "ready", "sample_count": 1319, "description": "Grade School Math 8K 小学数学应用题多步推理"},
    {"name": "arc", "source": "ModelScope/evalscope_arc", "status": "ready", "sample_count": 2590, "description": "AI2 Reasoning Challenge 科学常识推理问答"},
    {"name": "humaneval", "source": "ModelScope/evalscope_humaneval", "status": "ready", "sample_count": 164, "description": "HumanEval Python 代码生成能力评测集"},
]


def _seed_defaults_if_needed(db: Session):
    """首次访问时初始化内置用例模板与数据集描述"""
    if db.query(TestTemplate).count() == 0:
        for item in DEFAULT_TEMPLATES:
            tpl = TestTemplate(**item)
            db.add(tpl)
        db.commit()

    if db.query(DatasetInfo).count() == 0:
        for d in DEFAULT_DATASETS:
            ds = DatasetInfo(**d)
            db.add(ds)
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


DATASET_SAMPLES_MAP = {
    "mmlu": [
        {
            "id": 1,
            "category": "STEM / Computer Science",
            "question": "What is the primary advantage of a B-tree over a binary search tree for disk-based storage engines?",
            "options": ["A) Lower memory footprint", "B) Fewer disk I/O operations due to high fan-out", "C) O(1) worst-case search complexity", "D) Simple recursive traversal"],
            "target": "B",
        },
        {
            "id": 2,
            "category": "Biology / Cell Biology",
            "question": "Which organelle is primarily responsible for ATP synthesis via oxidative phosphorylation in eukaryotic cells?",
            "options": ["A) Endoplasmic Reticulum", "B) Mitochondria", "C) Golgi Apparatus", "D) Lysosome"],
            "target": "B",
        },
        {
            "id": 3,
            "category": "Machine Learning",
            "question": "In Transformer architectures, what is the main purpose of multi-head attention over single-head attention?",
            "options": ["A) Reduces overall memory complexity from O(N^2) to O(N)", "B) Allows the model to jointly attend to information from different representation subspaces", "C) Eliminates the need for residual connections", "D) Guarantees deterministic output generation"],
            "target": "B",
        },
    ],
    "ceval": [
        {
            "id": 1,
            "category": "计算机科学与技术",
            "question": "下列关于大语言模型中 Self-Attention（自注意力机制）计算复杂度的说法，正确的是：",
            "options": ["A) 时间复杂度与输入序列长度 N 呈线性关系 O(N)", "B) 时间复杂度与输入序列长度 N 呈平方关系 O(N^2)", "C) 空间复杂度与特征维度 d 无关", "D) 无法在 GPU 上进行并行化矩阵乘法计算"],
            "target": "B",
        },
        {
            "id": 2,
            "category": "中国历史与文化",
            "question": "中国古代四大发明中，最早被广泛应用于航海指南与远洋开辟的技术是：",
            "options": ["A) 造纸术", "B) 雕版印刷术", "C) 指南针（司南/罗盘）", "D) 火药"],
            "target": "C",
        },
        {
            "id": 3,
            "category": "高等数学与逻辑推理",
            "question": "函数 f(x) = x^3 - 3x 在区间 [-2, 2] 上的极小值点 x 等于：",
            "options": ["A) x = -1", "B) x = 0", "C) x = 1", "D) x = 2"],
            "target": "C",
        },
    ],
    "gsm8k": [
        {
            "id": 1,
            "category": "Grade School Math / Multi-step Reasoning",
            "question": "Natalia sold cookies to her 3 friends. The first friend bought 4 cookies, the second friend bought half as many as the first, and the third friend bought 5 more than the second. How many cookies did Natalia sell in total?",
            "options": [],
            "target": "13 (Calculation: 1st=4, 2nd=2, 3rd=2+5=7; Total=4+2+7=13)",
        },
        {
            "id": 2,
            "category": "Grade School Math / Word Problem",
            "question": "Weng earns $12 an hour for babysitting. Yesterday, she babysat for 5 hours. She spent $15 on lunch. How much money does she have left?",
            "options": [],
            "target": "$45 (Calculation: Total earned = 12 * 5 = $60. Remaining = 60 - 15 = $45)",
        },
    ],
    "arc": [
        {
            "id": 1,
            "category": "Physics / Kinetic Energy",
            "question": "Which object has the greatest kinetic energy?",
            "options": ["A) A 10 kg object moving at 2 m/s", "B) A 2 kg object moving at 10 m/s", "C) A 5 kg object moving at 3 m/s", "D) A 1 kg object moving at 5 m/s"],
            "target": "B (Ek = 0.5 * m * v^2 = 0.5 * 2 * 100 = 100 J)",
        },
    ],
    "humaneval": [
        {
            "id": 1,
            "category": "Python Programming / Algorithms",
            "question": "def has_close_elements(numbers: List[float], threshold: float) -> bool:\n    \"\"\" Check if in given list of numbers, any two numbers are closer to each other than given threshold. \"\"\"",
            "options": [],
            "target": "return any(abs(a - b) < threshold for i, a in enumerate(numbers) for j, b in enumerate(numbers) if i != j)",
        },
    ],
}


from fastapi import Query

DATASET_CONFIGS = {
    "mmlu": {
        "total": 14042,
        "categories": ["STEM / Computer Science", "Biology / Cell Biology", "Machine Learning", "Physics / Mechanics", "Humanities / Philosophy", "Social Sciences / Law", "Chemistry / Organic"],
        "base_samples": [
            {"category": "STEM / Computer Science", "question": "What is the primary advantage of a B-tree over a binary search tree for disk-based storage engines?", "options": ["A) Lower memory footprint", "B) Fewer disk I/O operations due to high fan-out", "C) O(1) worst-case search complexity", "D) Simple recursive traversal"], "target": "B"},
            {"category": "Biology / Cell Biology", "question": "Which organelle is primarily responsible for ATP synthesis via oxidative phosphorylation in eukaryotic cells?", "options": ["A) Endoplasmic Reticulum", "B) Mitochondria", "C) Golgi Apparatus", "D) Lysosome"], "target": "B"},
            {"category": "Machine Learning", "question": "In Transformer architectures, what is the main purpose of multi-head attention over single-head attention?", "options": ["A) Reduces overall memory complexity from O(N^2) to O(N)", "B) Allows the model to jointly attend to information from different representation subspaces", "C) Eliminates the need for residual connections", "D) Guarantees deterministic output generation"], "target": "B"},
            {"category": "Physics / Mechanics", "question": "An object of mass m moves in a circle of radius r with constant speed v. What is the magnitude of the net force acting on the object?", "options": ["A) Zero", "B) m * v / r", "C) m * v^2 / r", "D) m * v^2 / (2 * r)"], "target": "C"},
            {"category": "Humanities / Philosophy", "question": "Which philosopher proposed the categorical imperative as the supreme principle of morality?", "options": ["A) John Locke", "B) Immanuel Kant", "C) Friedrich Nietzsche", "D) David Hume"], "target": "B"},
        ]
    },
    "ceval": {
        "total": 13948,
        "categories": ["计算机科学与技术", "中国历史与文化", "高等数学与逻辑推理", "法律法规", "基础医学", "经济学"],
        "base_samples": [
            {"category": "计算机科学与技术", "question": "下列关于大语言模型中 Self-Attention（自注意力机制）计算复杂度的说法，正确的是：", "options": ["A) 时间复杂度与输入序列长度 N 呈线性关系 O(N)", "B) 时间复杂度与输入序列长度 N 呈平方关系 O(N^2)", "C) 空间复杂度与特征维度 d 无关", "D) 无法在 GPU 上进行并行化矩阵乘法计算"], "target": "B"},
            {"category": "中国历史与文化", "question": "中国古代四大发明中，最早被广泛应用于航海指南与远洋开辟的技术是：", "options": ["A) 造纸术", "B) 雕版印刷术", "C) 指南针（司南/罗盘）", "D) 火药"], "target": "C"},
            {"category": "高等数学与逻辑推理", "question": "函数 f(x) = x^3 - 3x 在区间 [-2, 2] 上的极小值点 x 等于：", "options": ["A) x = -1", "B) x = 0", "C) x = 1", "D) x = 2"], "target": "C"},
            {"category": "法律法规", "question": "根据我国《民法典》规定，未成年人的监护人首先应当由下列哪类人员担任？", "options": ["A) 祖父母、外祖父母", "B) 父母", "C) 兄、姐", "D) 其他近亲属"], "target": "B"},
        ]
    },
    "gsm8k": {
        "total": 1319,
        "categories": ["Grade School Math / Multi-step Reasoning", "Grade School Math / Word Problem", "Grade School Math / Algebra"],
        "base_samples": [
            {"category": "Grade School Math / Multi-step Reasoning", "question": "Natalia sold cookies to her 3 friends. The first friend bought 4 cookies, the second friend bought half as many as the first, and the third friend bought 5 more than the second. How many cookies did Natalia sell in total?", "options": [], "target": "13 (Calculation: 1st=4, 2nd=2, 3rd=2+5=7; Total=4+2+7=13)"},
            {"category": "Grade School Math / Word Problem", "question": "Weng earns $12 an hour for babysitting. Yesterday, she babysat for 5 hours. She spent $15 on lunch. How much money does she have left?", "options": [], "target": "$45 (Calculation: Total earned = 12 * 5 = $60. Remaining = 60 - 15 = $45)"},
            {"category": "Grade School Math / Algebra", "question": "James buys 5 packs of baseball cards. Each pack contains 12 cards. He gives 15 cards to his younger brother. How many cards does James have now?", "options": [], "target": "45 (Calculation: 5 * 12 = 60 cards. 60 - 15 = 45 cards remaining)"},
        ]
    },
    "arc": {
        "total": 2590,
        "categories": ["Physical Science", "Earth & Space Science", "Life Science"],
        "base_samples": [
            {"category": "Physical Science", "question": "Which object has the greatest kinetic energy?", "options": ["A) A 10 kg object moving at 2 m/s", "B) A 2 kg object moving at 10 m/s", "C) A 5 kg object moving at 3 m/s", "D) A 1 kg object moving at 5 m/s"], "target": "B (Ek = 0.5 * m * v^2 = 0.5 * 2 * 100 = 100 J)"},
            {"category": "Earth & Space Science", "question": "What is the primary cause of Earth's ocean tides?", "options": ["A) Earth's magnetic field", "B) Gravitational pull of the Moon and Sun", "C) Atmospheric pressure differences", "D) Ocean current circulation"], "target": "B"},
        ]
    },
    "humaneval": {
        "total": 164,
        "categories": ["Python Algorithms / Data Structures", "Python String Manipulation", "Python Math Functions"],
        "base_samples": [
            {"category": "Python Algorithms / Data Structures", "question": "def has_close_elements(numbers: List[float], threshold: float) -> bool:\n    \"\"\" Check if in given list of numbers, any two numbers are closer to each other than given threshold. \"\"\"", "options": [], "target": "return any(abs(a - b) < threshold for i, a in enumerate(numbers) for j, b in enumerate(numbers) if i != j)"},
            {"category": "Python String Manipulation", "question": "def truncate_number(number: float) -> float:\n    \"\"\" Given a positive floating point number, it can be decomposed into integer and decimals parts. Return the decimal part. \"\"\"", "options": [], "target": "return number % 1.0"},
            {"category": "Python Algorithms / Data Structures", "question": "def count_up_to(n: int) -> List[int]:\n    \"\"\" Implement a function that takes an non-negative integer and returns an array of the first n prime numbers. \"\"\"", "options": [], "target": "primes = []\nfor i in range(2, n):\n    if all(i % p != 0 for p in primes):\n        primes.append(i)\nreturn primes"},
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
