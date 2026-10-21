"""M7 weekly retrain, Kaggle side: LoRA fine-tune + GGUF export on a free GPU.

Pushed (private) by .github/workflows/retrain-domain-model.yml. Same recipe as
train_lora.ipynb; the data comes from a private Kaggle dataset written by
`python -m src.finetune.retrain prepare` (train.jsonl, val.jsonl, prompt.json).
The prompt is read from prompt.json, so it can't drift from src/finetune/prompt.py.

Only the GGUF is left in /kaggle/working (the kernel's downloadable output);
the evaluation gate runs back on GitHub Actions.
"""
import os

# Kaggle's T4 machine has two GPUs; Unsloth trains on one.
os.environ["CUDA_VISIBLE_DEVICES"] = "0"

OUTPUT = "/kaggle/working/marketingos-domain-q4_k_m.gguf"
SCRATCH = "/tmp/marketingos-domain"
# Work outside /kaggle/working so HF/Unsloth caches don't become kernel output.
os.makedirs(SCRATCH, exist_ok=True)
os.chdir(SCRATCH)
os.environ["HF_HOME"] = f"{SCRATCH}/hf"

import glob
import inspect
import json
import shutil
import subprocess
import sys

subprocess.run([sys.executable, "-m", "pip", "install", "-q", "unsloth"], check=True)

# Unsloth must be imported before trl/transformers to patch them.
from unsloth import FastLanguageModel  # noqa: E402
from unsloth.chat_templates import get_chat_template, train_on_responses_only  # noqa: E402
from datasets import Dataset  # noqa: E402
from trl import SFTConfig, SFTTrainer  # noqa: E402


def find(name: str) -> str:
    matches = glob.glob(f"/kaggle/input/**/{name}", recursive=True)
    assert matches, f"{name} not found under /kaggle/input"
    return matches[0]


def load(name: str) -> list[dict]:
    with open(find(name), encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


prompt = json.load(open(find("prompt.json"), encoding="utf-8"))
SYSTEM, CATEGORIES = prompt["system"], prompt["categories"]
train_rows, val_rows = load("train.jsonl"), load("val.jsonl")
print(f"train {len(train_rows)} | val {len(val_rows)}", flush=True)


def build_messages(idea: str) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"Categories: {', '.join(CATEGORIES)}\nIdea: {idea.strip()}\nCategory:"},
    ]


model, tokenizer = FastLanguageModel.from_pretrained(
    model_name="unsloth/Qwen2.5-1.5B-Instruct", max_seq_length=512, load_in_4bit=True
)
tokenizer = get_chat_template(tokenizer, chat_template="qwen-2.5")
model = FastLanguageModel.get_peft_model(
    model,
    r=16,
    lora_alpha=16,
    lora_dropout=0,
    target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
    bias="none",
    use_gradient_checkpointing="unsloth",
    random_state=7,
)


def to_text(row: dict) -> dict:
    messages = build_messages(row["idea"]) + [{"role": "assistant", "content": row["label"]}]
    return {"text": tokenizer.apply_chat_template(messages, tokenize=False)}


columns = ["idea", "label"]
train_ds = Dataset.from_list([{k: r[k] for k in columns} for r in train_rows]).map(to_text)
val_ds = Dataset.from_list([{k: r[k] for k in columns} for r in val_rows]).map(to_text)

seq_len_arg = "max_length" if "max_length" in inspect.signature(SFTConfig).parameters else "max_seq_length"
trainer = SFTTrainer(
    model=model,
    processing_class=tokenizer,
    train_dataset=train_ds,
    eval_dataset=val_ds,
    args=SFTConfig(
        dataset_text_field="text",
        # TRL renamed max_seq_length -> max_length; Kaggle installs whatever is latest.
        **{seq_len_arg: 512},
        per_device_train_batch_size=8,
        gradient_accumulation_steps=2,
        num_train_epochs=3,
        learning_rate=2e-4,
        warmup_ratio=0.05,
        lr_scheduler_type="linear",
        optim="adamw_8bit",
        weight_decay=0.01,
        logging_steps=10,
        eval_strategy="epoch",
        seed=7,
        output_dir=f"{SCRATCH}/outputs",
        report_to="none",
    ),
)
trainer = train_on_responses_only(trainer, instruction_part="<|im_start|>user\n", response_part="<|im_start|>assistant\n")
trainer.train()

# Export to scratch (the merged 16-bit weights are GBs), keep only the GGUF.
model.save_pretrained_gguf(f"{SCRATCH}/gguf", tokenizer, quantization_method="q4_k_m")
gguf = sorted(glob.glob(f"{SCRATCH}/gguf*/*.gguf") + glob.glob("*.gguf"))
quantized = [p for p in gguf if "q4_k_m" in p.lower()] or gguf
assert quantized, "GGUF export produced no file"
shutil.move(quantized[0], OUTPUT)
print(f"wrote {OUTPUT} ({os.path.getsize(OUTPUT) / 1e6:.0f} MB)", flush=True)
