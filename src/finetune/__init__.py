"""M7: distil the idea_intake domain classifier into a small LoRA-tuned model.

generate_dataset.py  -> synthetic, teacher-labelled train/val/test (committed)
export_dataset.py    -> real campaigns (git-ignored; users' content)
train_lora.ipynb     -> Unsloth LoRA on Colab, exports a 4-bit GGUF
evaluate_finetune.py -> teacher vs base vs fine-tuned, side by side
"""
