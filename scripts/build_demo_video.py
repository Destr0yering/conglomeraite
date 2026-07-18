#!/usr/bin/env python3
"""Build the evidence-based ConglomerAIte demo video without model calls."""

from __future__ import annotations

import argparse
import json
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps


ROOT = Path(__file__).resolve().parents[1]
WIDTH, HEIGHT = 1920, 1080
BG = "#07131f"
PANEL = "#102637"
TEAL = "#23d5c3"
GOLD = "#f7b955"
PURPLE = "#a785ff"
WHITE = "#f4f8fb"
MUTED = "#a9bac7"


def font(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    filename = "seguisb.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / filename), size)


def wrapped(draw: ImageDraw.ImageDraw, text: str, box: tuple[int, int, int, int], *,
            size: int, color: str = WHITE, bold: bool = False, spacing: int = 16) -> int:
    x1, y1, x2, _ = box
    face = font(size, bold=bold)
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if draw.textbbox((0, 0), candidate, font=face)[2] <= x2 - x1:
            line = candidate
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    y = y1
    for line in lines:
        draw.text((x1, y), line, font=face, fill=color)
        y += size + spacing
    return y


def base_slide(kicker: str, title: str, number: str) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((56, 50, 1864, 1030), radius=34, fill=PANEL, outline="#1e465d", width=2)
    draw.rectangle((56, 50, 1864, 64), fill=TEAL)
    draw.text((110, 100), kicker.upper(), font=font(28, bold=True), fill=TEAL)
    draw.text((110, 150), title, font=font(60, bold=True), fill=WHITE)
    draw.text((1770, 100), number, font=font(28, bold=True), fill=MUTED)
    return image, draw


def fit_image(path: Path, size: tuple[int, int], *, contain: bool = True) -> Image.Image:
    image = Image.open(path).convert("RGB")
    method = Image.Resampling.LANCZOS
    if contain:
        image.thumbnail(size, method)
        canvas = Image.new("RGB", size, "#091925")
        canvas.paste(image, ((size[0] - image.width) // 2, (size[1] - image.height) // 2))
        return canvas
    return ImageOps.fit(image, size, method=method)


def save(image: Image.Image, output: Path, name: str) -> Path:
    path = output / name
    image.save(path, format="PNG", optimize=True)
    return path


def build_slides(output: Path) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    slides: list[Path] = []

    # 1 — title and topology
    image = fit_image(ROOT / "artifacts/architecture-diagram.png", (WIDTH, HEIGHT), contain=False)
    image = ImageEnhance.Brightness(image).enhance(0.34).filter(ImageFilter.GaussianBlur(2))
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), "#05111dcc")
    image = Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((135, 180, 1785, 900), radius=42, fill="#07131fe8", outline=TEAL, width=3)
    draw.text((220, 260), "THE CONGLOMERAITE™", font=font(44, bold=True), fill=TEAL)
    wrapped(draw, "Fault-Tolerant Swarm Intelligence", (220, 355, 1680, 600), size=78, bold=True)
    wrapped(draw, "QwenCloud reasoning. Jetson edge continuity. Bounded autonomous self-correction.",
            (225, 650, 1630, 820), size=38, color=MUTED)
    slides.append(save(image, output, "01-title.png"))

    # 2 — architecture
    image, draw = base_slide("Track 5 EdgeAgent + Track 3 Agent Society", "One task. Two routes. Bounded refinement.", "02")
    diagram = fit_image(ROOT / "artifacts/architecture-diagram.png", (1690, 720))
    image.paste(diagram, (115, 250))
    slides.append(save(image, output, "02-architecture.png"))

    # 3 — 10/10 loop
    image, draw = base_slide("Autonomous correction", "The 10/10 contract is strict—and finite.", "03")
    cards = [
        ("GENERATOR", "Creates a candidate against an immutable rubric.", TEAL),
        ("CRITIC", "Returns structured score, blockers, and targeted refinements.", PURPLE),
        ("GATE", "Only a valid 10/10 with zero blockers reaches consensus.", GOLD),
    ]
    x = 105
    for heading, body, accent in cards:
        draw.rounded_rectangle((x, 300, x + 525, 625), radius=28, fill="#0b1b28", outline=accent, width=3)
        draw.text((x + 38, 350), heading, font=font(34, bold=True), fill=accent)
        wrapped(draw, body, (x + 38, 430, x + 480, 590), size=29, color=WHITE)
        x += 590
    draw.line((400, 715, 1520, 715), fill="#31536a", width=8)
    draw.ellipse((360, 675, 440, 755), fill=GOLD)
    draw.ellipse((1480, 675, 1560, 755), fill=TEAL)
    draw.text((318, 785), "Round 1: 8/10", font=font(36, bold=True), fill=GOLD)
    draw.text((1395, 785), "Round 2: 10/10", font=font(36, bold=True), fill=TEAL)
    draw.text((560, 890), "Circuit breakers: time • iterations • stagnation • provider • RAM", font=font(32), fill=MUTED)
    slides.append(save(image, output, "03-loop.png"))

    # 4 — Nano proof
    nano = json.loads((ROOT / "evidence/nano-outage-demo.summary.json").read_text(encoding="utf-8"))
    image, draw = base_slide("Physical edge proof", "Forced cloud loss on the Jetson Orin Nano", "04")
    metrics = [
        ("0", "paid cloud calls"),
        (str(nano["degraded_calls"]), "degraded local calls"),
        (f'{nano["final_score"]:.0f}/10', "best candidate retained"),
        ("0", "model restarts"),
    ]
    x = 110
    for value, label in metrics:
        draw.rounded_rectangle((x, 300, x + 390, 545), radius=26, fill="#0a1c29", outline="#2c5369", width=2)
        draw.text((x + 36, 340), value, font=font(76, bold=True), fill=TEAL if value != "8/10" else GOLD)
        wrapped(draw, label, (x + 36, 445, x + 355, 535), size=27, color=MUTED)
        x += 430
    draw.rounded_rectangle((110, 625, 1810, 925), radius=28, fill="#091925", outline=PURPLE, width=2)
    wrapped(draw, "Cloud endpoint forced to closed loopback 127.0.0.1:1. The router attempted cloud, opened the breaker, moved two logical roles through the loopback-only SYSOP bridge, and stopped honestly at the 125.7-second provider/deadline boundary.",
            (165, 685, 1760, 870), size=34, color=WHITE, spacing=20)
    slides.append(save(image, output, "04-nano.png"))

    # 5 — memory containment
    safety = nano["nano_safety"]
    image, draw = base_slide("Hardware-safe degradation", "Contain the model. Preserve the orchestrator.", "05")
    left = [
        ("MemoryHigh", f'{safety["llama_memory_high_bytes"] / 2**30:.2f} GiB'),
        ("MemoryMax", f'{safety["llama_memory_max_bytes"] / 2**30:.2f} GiB'),
        ("MemorySwapMax", f'{safety["llama_memory_swap_max_bytes"] / 2**30:.0f} GiB'),
        ("OOMScoreAdjust", str(safety["llama_oom_score_adjust"])),
    ]
    y = 295
    for label, value in left:
        draw.rounded_rectangle((120, y, 850, y + 125), radius=20, fill="#0a1c29")
        draw.text((165, y + 31), label, font=font(30, bold=True), fill=MUTED)
        draw.text((620, y + 22), value, font=font(42, bold=True), fill=TEAL)
        y += 145
    draw.rounded_rectangle((940, 295, 1780, 875), radius=28, fill="#0a1c29", outline=GOLD, width=3)
    draw.text((1000, 355), "POST-RUN STATE", font=font(32, bold=True), fill=GOLD)
    draw.text((1000, 455), f'{safety["available_ram_mb_after"]:,} MB', font=font(72, bold=True), fill=WHITE)
    draw.text((1000, 545), "available RAM", font=font(31), fill=MUTED)
    draw.text((1000, 655), f'{safety["swap_used_mb_after"]:,} MB', font=font(72, bold=True), fill=WHITE)
    draw.text((1000, 745), "swap in use", font=font(31), fill=MUTED)
    draw.text((110, 950), "Admission checks reduce risk; they do not claim to reserve CUDA memory or prevent every driver-level OOM.", font=font(28), fill=MUTED)
    slides.append(save(image, output, "05-safety.png"))

    # 6 — Alibaba proof
    image, draw = base_slide("Alibaba-hosted proof", "Signed metadata only. Content stays out.", "06")
    workbench = fit_image(ROOT / "artifacts/alibaba-function-workbench-proof.png", (820, 585), contain=False)
    trigger = fit_image(ROOT / "artifacts/alibaba-function-trigger-auth-proof.png", (820, 585), contain=False)
    image.paste(workbench, (110, 270))
    image.paste(trigger, (990, 270))
    for x, code, label, color in [(155, "200", "health", TEAL), (645, "401", "unsigned rejected", GOLD), (1190, "202", "signed accepted", PURPLE)]:
        draw.rounded_rectangle((x, 880, x + 410, 995), radius=22, fill="#091925", outline=color, width=3)
        draw.text((x + 35, 902), code, font=font(48, bold=True), fill=color)
        draw.text((x + 155, 919), label, font=font(25), fill=WHITE)
    slides.append(save(image, output, "06-alibaba.png"))

    # 7 — evidence discipline
    image, draw = base_slide("Measured, not marketed", "Claims are bounded by the evidence.", "07")
    draw.rounded_rectangle((115, 300, 910, 880), radius=30, fill="#0a1c29", outline=TEAL, width=3)
    draw.text((175, 365), "PROVED", font=font(36, bold=True), fill=TEAL)
    proved = [
        "Cloud-to-edge routing under forced failure",
        "Best-candidate retention at a safe boundary",
        "Sequential Generator/Critic roles on one edge model",
        "HMAC receiver acceptance and rejection paths",
    ]
    y = 455
    for item in proved:
        draw.ellipse((175, y + 9, 197, y + 31), fill=TEAL)
        y = wrapped(draw, item, (220, y, 850, y + 100), size=29, color=WHITE) + 32
    draw.rounded_rectangle((1010, 300, 1805, 880), radius=30, fill="#0a1c29", outline=GOLD, width=3)
    draw.text((1070, 365), "NOT OVERCLAIMED", font=font(36, bold=True), fill=GOLD)
    limits = [
        "The edge run stopped at 8/10—not consensus",
        "The three-task pilot is not universal superiority",
        "Systemd ceilings are not CUDA reservations",
        "The receiver is optional, not an offline dependency",
    ]
    y = 455
    for item in limits:
        draw.ellipse((1070, y + 9, 1092, y + 31), fill=GOLD)
        y = wrapped(draw, item, (1115, y, 1740, y + 100), size=29, color=WHITE) + 32
    slides.append(save(image, output, "07-claims.png"))

    # 8 — close
    image, draw = base_slide("CONGLOMERAITE™", "Graceful degradation is a capability—not an apology.", "08")
    wrapped(draw, "Cloud intelligence when available. Edge continuity when it is not. Autonomous refinement bounded by hardware reality.",
            (180, 350, 1740, 650), size=57, bold=True, spacing=24)
    draw.rounded_rectangle((180, 760, 1740, 895), radius=28, fill="#0a1c29", outline=TEAL, width=3)
    draw.text((285, 800), "github.com/Destr0yering/conglomeraite", font=font(42, bold=True), fill=TEAL)
    draw.text((685, 945), "QwenCloud Global AI Hackathon • Track 5", font=font(30), fill=MUTED)
    slides.append(save(image, output, "08-close.png"))

    return slides


def audio_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as audio:
        return audio.getnframes() / audio.getframerate()


def build_video(ffmpeg: Path, slides: list[Path], narration: Path, output: Path) -> None:
    duration = audio_seconds(narration)
    if duration > 177:
        raise SystemExit(f"narration is too long ({duration:.1f}s); must be <=177s")
    total = max(155.0, duration + 2.0)
    weights = [0.07, 0.12, 0.15, 0.16, 0.13, 0.14, 0.13, 0.10]
    concat = output.parent / "demo-slides.txt"
    lines: list[str] = []
    for slide, weight in zip(slides, weights, strict=True):
        safe = slide.resolve().as_posix().replace("'", "'\\''")
        lines.extend([f"file '{safe}'", f"duration {total * weight:.3f}"])
    lines.append(f"file '{slides[-1].resolve().as_posix()}'")
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = [
        str(ffmpeg), "-y", "-f", "concat", "-safe", "0", "-i", str(concat),
        "-i", str(narration), "-vf", "fps=30,format=yuv420p", "-c:v", "libx264",
        "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", "-shortest", str(output),
    ]
    subprocess.run(command, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--narration", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    slide_dir = args.output.parent / "demo-slides"
    slides = build_slides(slide_dir)
    build_video(args.ffmpeg, slides, args.narration, args.output)
    print(json.dumps({"output": str(args.output), "slides": len(slides), "duration_seconds": round(audio_seconds(args.narration), 2)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
