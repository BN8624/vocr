# 카드 명세서 PDF를 Excel로 변환하는 PC 전용 GUI
from __future__ import annotations

import queue
import subprocess
import sys
import threading
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from review import _safe_output_name


DEFAULT_OUTPUT_ROOT = "output/converted"


STAGES: list[tuple[str, str, int]] = [
    ("render", "PDF 페이지 준비", 8),
    ("extract", "AI 표 읽기", 35),
    ("merge", "행 정리", 50),
    ("mapping", "열 역할 판정", 62),
    ("normalize", "거래 정규화", 74),
    ("validate", "검산 및 검증", 84),
    ("excel", "Excel 생성", 94),
    ("review", "결과 정리", 98),
    ("done", "완료", 100),
]


STAGE_PATTERNS: list[tuple[str, str]] = [
    ("Rendering PDF pages", "render"),
    ("Page-mode extraction", "extract"),
    ("Extracting rows", "extract"),
    ("Dry-run mode", "extract"),
    ("Collecting raw rows", "merge"),
    ("Building column mapping", "mapping"),
    ("Normalizing mapped rows", "normalize"),
    ("Validating normalized transactions", "validate"),
    ("Exporting reviewable Excel", "excel"),
    ("Building review HTML", "review"),
    ("Done. Review file", "done"),
]


@dataclass(frozen=True)
class Job:
    pdf_path: Path
    output_dir: Path


def stage_for_line(line: str) -> str | None:
    for pattern, stage in STAGE_PATTERNS:
        if pattern in line:
            return stage
    return None


def stage_percent(stage: str) -> int:
    for key, _label, percent in STAGES:
        if key == stage:
            return percent
    return 0


def stage_label(stage: str) -> str:
    for key, label, _percent in STAGES:
        if key == stage:
            return label
    return "대기"


def build_command(repo_root: Path, job: Job, *, dry_run: bool, force_vision: bool) -> list[str]:
    command = [
        sys.executable,
        str(repo_root / "main.py"),
        "--input",
        str(job.pdf_path),
        "--output",
        str(job.output_dir),
        "--config",
        str(repo_root / "config.yaml"),
        "--extraction-mode",
        "page",
    ]
    if dry_run:
        command.append("--dry-run")
    if force_vision:
        command.append("--force-vision")
    return command


class ConverterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.repo_root = Path(__file__).resolve().parent
        self.title("카드 명세서 Excel 변환")
        self.geometry("860x620")
        self.minsize(760, 560)

        self.jobs: list[Job] = []
        self.current_process: subprocess.Popen[str] | None = None
        self.output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.running = False
        self.blink_on = True
        self.latest_excel: Path | None = None

        self.input_var = tk.StringVar(value="선택된 PDF 없음")
        self.output_var = tk.StringVar(value=str((self.repo_root / DEFAULT_OUTPUT_ROOT).resolve()))
        self.status_var = tk.StringVar(value="대기")
        self.current_var = tk.StringVar(value="시작 전")
        self.percent_var = tk.IntVar(value=0)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.force_vision_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.after(100, self._drain_queue)
        self.after(500, self._blink_current_stage)

    def _build_ui(self) -> None:
        self.configure(bg="#edf2f0")
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text="카드 명세서 Excel 변환", font=("Malgun Gothic", 18, "bold"))
        title.pack(anchor="w")
        subtitle = ttk.Label(outer, text="PDF를 선택하고 시작을 누르면 result.xlsx가 생성됩니다.")
        subtitle.pack(anchor="w", pady=(2, 18))

        controls = ttk.Frame(outer)
        controls.pack(fill="x")

        ttk.Button(controls, text="PDF 선택", command=self.select_pdfs).grid(row=0, column=0, sticky="w")
        ttk.Label(controls, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=10)

        ttk.Button(controls, text="출력 폴더", command=self.select_output_root).grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Label(controls, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=10, pady=(8, 0))
        controls.columnconfigure(1, weight=1)

        options = ttk.Frame(outer)
        options.pack(fill="x", pady=(14, 0))
        ttk.Checkbutton(options, text="기존 cache만 사용", variable=self.dry_run_var).pack(side="left")
        ttk.Checkbutton(options, text="AI 재호출 강제", variable=self.force_vision_var).pack(side="left", padx=(18, 0))

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(18, 0))
        self.start_button = ttk.Button(actions, text="시작", command=self.start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="중지", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.open_excel_button = ttk.Button(actions, text="Excel 열기", command=self.open_excel, state="disabled")
        self.open_excel_button.pack(side="right")
        self.open_folder_button = ttk.Button(actions, text="폴더 열기", command=self.open_folder, state="disabled")
        self.open_folder_button.pack(side="right", padx=(0, 8))

        progress_box = ttk.LabelFrame(outer, text="진행상황", padding=12)
        progress_box.pack(fill="x", pady=(18, 0))
        top_line = ttk.Frame(progress_box)
        top_line.pack(fill="x")
        ttk.Label(top_line, textvariable=self.status_var, font=("Malgun Gothic", 11, "bold")).pack(side="left")
        self.current_label = ttk.Label(top_line, textvariable=self.current_var)
        self.current_label.pack(side="right")
        self.progress = ttk.Progressbar(progress_box, maximum=100, variable=self.percent_var, mode="determinate")
        self.progress.pack(fill="x", pady=(10, 4))

        stage_line = ttk.Frame(progress_box)
        stage_line.pack(fill="x")
        for _key, label, _percent in STAGES:
            ttk.Label(stage_line, text=label, font=("Malgun Gothic", 8)).pack(side="left", expand=True)

        log_box = ttk.LabelFrame(outer, text="로그", padding=8)
        log_box.pack(fill="both", expand=True, pady=(18, 0))
        self.log_text = tk.Text(log_box, height=14, wrap="word", state="disabled", bg="#fbfbfb", relief="flat")
        scroll = ttk.Scrollbar(log_box, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def select_pdfs(self) -> None:
        paths = filedialog.askopenfilenames(
            title="변환할 PDF 선택",
            filetypes=[("PDF files", "*.pdf")],
        )
        if not paths:
            return
        output_root = Path(self.output_var.get())
        self.jobs = [
            Job(Path(path), output_root / _safe_output_name(Path(path)))
            for path in paths
        ]
        if len(self.jobs) == 1:
            self.input_var.set(str(self.jobs[0].pdf_path))
        else:
            self.input_var.set(f"{len(self.jobs)}개 PDF 선택됨")
        self._reset_result_buttons()

    def select_output_root(self) -> None:
        path = filedialog.askdirectory(title="출력 루트 폴더 선택")
        if not path:
            return
        self.output_var.set(path)
        if self.jobs:
            output_root = Path(path)
            self.jobs = [Job(job.pdf_path, output_root / _safe_output_name(job.pdf_path)) for job in self.jobs]
        self._reset_result_buttons()

    def start(self) -> None:
        if self.running:
            return
        if not self.jobs:
            messagebox.showwarning("PDF 선택 필요", "먼저 변환할 PDF를 선택하세요.")
            return
        self.running = True
        self.latest_excel = None
        self.percent_var.set(0)
        self.status_var.set("작업 시작")
        self.current_var.set("준비 중")
        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self._reset_result_buttons()
        self._clear_log()
        self.worker = threading.Thread(target=self._run_jobs, daemon=True)
        self.worker.start()

    def cancel(self) -> None:
        process = self.current_process
        if process and process.poll() is None:
            process.terminate()
            self._append_log("중지 요청을 보냈습니다.")
        self.running = False

    def open_excel(self) -> None:
        if self.latest_excel and self.latest_excel.exists():
            subprocess.Popen(["cmd", "/c", "start", "", str(self.latest_excel)])

    def open_folder(self) -> None:
        if self.latest_excel:
            subprocess.Popen(["explorer", str(self.latest_excel.parent)])

    def _run_jobs(self) -> None:
        try:
            for index, job in enumerate(self.jobs, start=1):
                if not self.running:
                    break
                self.output_queue.put(("status", f"{index}/{len(self.jobs)} 변환 중"))
                self.output_queue.put(("stage", "render"))
                self.output_queue.put(("log", f"[{index}/{len(self.jobs)}] {job.pdf_path}"))
                code = self._run_one(job)
                if code != 0:
                    self.output_queue.put(("error", f"실패: {job.pdf_path.name} (exit {code})"))
                    return
                excel = job.output_dir / "result.xlsx"
                if not excel.exists():
                    self.output_queue.put(("error", f"Excel 파일이 생성되지 않았습니다: {excel}"))
                    return
                self.latest_excel = excel
                self.output_queue.put(("log", f"Excel 생성: {excel}"))
            if self.running:
                self.output_queue.put(("stage", "done"))
                self.output_queue.put(("complete", "변환 완료"))
        finally:
            self.running = False

    def _run_one(self, job: Job) -> int:
        command = build_command(
            self.repo_root,
            job,
            dry_run=bool(self.dry_run_var.get()),
            force_vision=bool(self.force_vision_var.get()),
        )
        self.current_process = subprocess.Popen(
            command,
            cwd=self.repo_root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self.current_process.stdout is not None
        for line in self.current_process.stdout:
            clean = line.rstrip()
            if clean:
                self.output_queue.put(("log", clean))
                stage = stage_for_line(clean)
                if stage:
                    self.output_queue.put(("stage", stage))
        return self.current_process.wait()

    def _drain_queue(self) -> None:
        while True:
            try:
                kind, value = self.output_queue.get_nowait()
            except queue.Empty:
                break
            if kind == "log":
                self._append_log(value)
            elif kind == "stage":
                self._set_stage(value)
            elif kind == "status":
                self.status_var.set(value)
            elif kind == "error":
                self._append_log(value)
                self.status_var.set("실패")
                self.current_var.set(value)
                self.start_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                messagebox.showerror("변환 실패", value)
            elif kind == "complete":
                self.status_var.set(value)
                self.current_var.set("완료")
                self.percent_var.set(100)
                self.start_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                self.open_excel_button.configure(state="normal")
                self.open_folder_button.configure(state="normal")
        self.after(100, self._drain_queue)

    def _set_stage(self, stage: str) -> None:
        self.percent_var.set(max(self.percent_var.get(), stage_percent(stage)))
        self.current_var.set(f"현재: {stage_label(stage)}")

    def _append_log(self, line: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{time.strftime('%H:%M:%S')}  {line}\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def _blink_current_stage(self) -> None:
        if self.running:
            self.blink_on = not self.blink_on
            self.current_label.configure(foreground="#1e6644" if self.blink_on else "#edf2f0")
        else:
            self.current_label.configure(foreground="#1e6644")
            self.blink_on = True
        self.after(500, self._blink_current_stage)

    def _reset_result_buttons(self) -> None:
        self.open_excel_button.configure(state="disabled")
        self.open_folder_button.configure(state="disabled")


def main() -> int:
    app = ConverterApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
