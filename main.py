import csv
import time
import tkinter as tk
from dataclasses import dataclass, field, asdict
from datetime import datetime
from tkinter import ttk, filedialog, messagebox
from typing import Callable, Dict, List, Optional


@dataclass
class ContextParameters:
    target_person: str = "Surgeon"
    instrument_type: str = "Forceps"
    urgency_level: str = "Normal"
    side_direction: str = "Center"
    speed_profile: str = "Standard"


@dataclass
class ActionRequest:
    action: str
    params: ContextParameters
    selected_at: float


@dataclass
class LogEntry:
    timestamp: str
    event_type: str
    details: str
    latency_ms: float = 0.0
    duration_ms: float = 0.0
    scenario: str = ""
    mode: str = ""


@dataclass
class Scenario:
    name: str
    description: str
    preload_params: ContextParameters
    recommended_actions: List[str]


class EventLogger:
    def __init__(self):
        self.entries: List[LogEntry] = []

    def log(self, event_type: str, details: str, scenario: str, mode: str,
            latency_ms: float = 0.0, duration_ms: float = 0.0) -> LogEntry:
        entry = LogEntry(
            timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            event_type=event_type,
            details=details,
            latency_ms=latency_ms,
            duration_ms=duration_ms,
            scenario=scenario,
            mode=mode,
        )
        self.entries.append(entry)
        return entry

    def export_csv(self, path: str) -> None:
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "timestamp", "event_type", "details", "latency_ms",
                    "duration_ms", "scenario", "mode"
                ],
            )
            writer.writeheader()
            for e in self.entries:
                writer.writerow(asdict(e))


class RobotSimulator:
    VALID_STATES = ["idle", "ready", "executing", "paused", "error", "emergency stop"]

    def __init__(self, on_state_change: Callable[[], None], logger: EventLogger):
        self.state = "ready"
        self.current_action: Optional[ActionRequest] = None
        self.queue: List[ActionRequest] = []
        self.completed: List[str] = []
        self.on_state_change = on_state_change
        self.logger = logger
        self._tk_root: Optional[tk.Tk] = None
        self._after_token = None
        self._execution_started_at = 0.0

    def bind_root(self, root: tk.Tk) -> None:
        self._tk_root = root

    def select_and_queue(self, request: ActionRequest) -> None:
        if self.state in {"error", "emergency stop"}:
            return
        if self.current_action is None:
            self.queue.insert(0, request)
        else:
            self.queue.append(request)
        self.on_state_change()

    def execute_next(self, scenario: str, mode: str) -> None:
        if self.state in {"error", "emergency stop"}:
            return
        if self.current_action is not None or not self.queue:
            return
        self.current_action = self.queue.pop(0)
        self.state = "executing"
        self._execution_started_at = time.time()
        latency_ms = (self._execution_started_at - self.current_action.selected_at) * 1000
        duration_ms = self._estimate_duration_ms(self.current_action)
        self.logger.log(
            "action_execution",
            self._describe_action(self.current_action),
            scenario=scenario,
            mode=mode,
            latency_ms=latency_ms,
            duration_ms=duration_ms,
        )
        self.on_state_change()
        if self._tk_root is not None:
            self._after_token = self._tk_root.after(int(duration_ms), lambda: self._complete_current(scenario, mode))

    def _complete_current(self, scenario: str, mode: str) -> None:
        if self.current_action is None or self.state != "executing":
            return
        duration_ms = (time.time() - self._execution_started_at) * 1000
        desc = self._describe_action(self.current_action)
        self.completed.insert(0, f"{self.current_action.action} ({duration_ms:.0f}ms)")
        self.completed = self.completed[:8]
        self.logger.log("action_completed", desc, scenario=scenario, mode=mode, duration_ms=duration_ms)
        self.current_action = None
        self.state = "ready"
        self._after_token = None
        self.on_state_change()

    def cancel_current(self, scenario: str, mode: str) -> None:
        if self.state == "executing" and self.current_action is not None:
            if self._tk_root is not None and self._after_token is not None:
                self._tk_root.after_cancel(self._after_token)
            desc = self._describe_action(self.current_action)
            self.logger.log("action_cancelled", desc, scenario=scenario, mode=mode)
            self.current_action = None
            self.state = "ready"
            self._after_token = None
            self.on_state_change()

    def emergency_stop(self, scenario: str, mode: str) -> None:
        if self._tk_root is not None and self._after_token is not None:
            self._tk_root.after_cancel(self._after_token)
        self._after_token = None
        self.state = "emergency stop"
        self.current_action = None
        self.logger.log("emergency_stop", "Emergency stop engaged", scenario=scenario, mode=mode)
        self.on_state_change()

    def set_error(self, message: str, scenario: str, mode: str) -> None:
        self.state = "error"
        self.logger.log("error", message, scenario=scenario, mode=mode)
        self.on_state_change()

    def reset(self, scenario: str, mode: str) -> None:
        if self._tk_root is not None and self._after_token is not None:
            self._tk_root.after_cancel(self._after_token)
        self._after_token = None
        self.state = "ready"
        self.current_action = None
        self.logger.log("state_reset", "Robot state reset", scenario=scenario, mode=mode)
        self.on_state_change()

    def clear_queue(self, scenario: str, mode: str) -> None:
        self.queue.clear()
        self.logger.log("queue_cleared", "Pending queue cleared", scenario=scenario, mode=mode)
        self.on_state_change()

    @staticmethod
    def _estimate_duration_ms(request: ActionRequest) -> int:
        base = {
            "Handover item": 2400,
            "Move to standby": 1300,
            "Approach operator": 1600,
            "Retract / retreat": 1500,
            "Hold position": 800,
            "Return to safe pose": 1800,
            "Cancel current action": 500,
        }.get(request.action, 1200)
        urgency_mod = {"Low": 200, "Normal": 0, "High": -250, "Critical": -500}
        speed_mod = {"Slow": 300, "Standard": 0, "Fast": -300}
        return max(400, base + urgency_mod.get(request.params.urgency_level, 0) + speed_mod.get(request.params.speed_profile, 0))

    @staticmethod
    def _describe_action(request: ActionRequest) -> str:
        p = request.params
        return (
            f"{request.action} | target={p.target_person}, instrument={p.instrument_type}, "
            f"urgency={p.urgency_level}, side={p.side_direction}, speed={p.speed_profile}"
        )


class WoZApp(tk.Tk):
    ACTION_CATEGORIES: Dict[str, List[str]] = {
        "Primary": ["Handover item", "Approach operator", "Move to standby"],
        "Positioning": ["Retract / retreat", "Hold position", "Return to safe pose"],
        "Control": ["Cancel current action"],
    }

    def __init__(self):
        super().__init__()
        self.title("WoZ Medical Assistive Arm Wizard Interface (Prototype)")
        self.geometry("1400x860")
        self.minsize(1200, 760)

        self.logger = EventLogger()
        self.mode_var = tk.StringVar(value="Study")
        self.selected_action_var = tk.StringVar(value="No action selected")
        self.status_var = tk.StringVar(value="ready")

        self.context = ContextParameters()
        self.scenarios = self._build_scenarios()
        self.scenario_var = tk.StringVar(value=self.scenarios[0].name)

        self.robot = RobotSimulator(self.refresh_state, self.logger)
        self.robot.bind_root(self)

        self.param_vars: Dict[str, tk.StringVar] = {}
        self.log_text: Optional[tk.Text] = None
        self.recommended_text: Optional[tk.Text] = None

        self._build_ui()
        self._bind_shortcuts()
        self.load_scenario(self.scenario_var.get(), initial=True)
        self.refresh_state()

    def _build_scenarios(self) -> List[Scenario]:
        return [
            Scenario(
                "Simple handover",
                "Routine handover from standby to clinician and back.",
                ContextParameters("Surgeon", "Scalpel", "Normal", "Right", "Standard"),
                ["Approach operator", "Handover item", "Retract / retreat", "Move to standby"],
            ),
            Scenario(
                "Interrupted handover",
                "Start handover then cancel and return to safe posture.",
                ContextParameters("Nurse", "Syringe", "High", "Left", "Fast"),
                ["Approach operator", "Handover item", "Cancel current action", "Return to safe pose"],
            ),
            Scenario(
                "Urgent reprioritization",
                "Urgent request arrives while managing current positioning.",
                ContextParameters("Lead Surgeon", "Clamp", "Critical", "Center", "Fast"),
                ["Hold position", "Cancel current action", "Approach operator", "Handover item"],
            ),
        ]

    def _build_ui(self):
        self.columnconfigure(0, weight=3)
        self.columnconfigure(1, weight=4)
        self.columnconfigure(2, weight=3)
        self.rowconfigure(0, weight=8)
        self.rowconfigure(1, weight=3)

        left = ttk.LabelFrame(self, text="Live Control (Quick Actions)")
        left.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        self._build_left_panel(left)

        center = ttk.LabelFrame(self, text="Robot State & Execution")
        center.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        self._build_center_panel(center)

        right = ttk.LabelFrame(self, text="Scenario + Context + Mode")
        right.grid(row=0, column=2, sticky="nsew", padx=6, pady=6)
        self._build_right_panel(right)

        bottom = ttk.LabelFrame(self, text="Event Logs")
        bottom.grid(row=1, column=0, columnspan=3, sticky="nsew", padx=6, pady=6)
        self._build_bottom_panel(bottom)

    def _build_left_panel(self, parent):
        row = 0
        for cat, actions in self.ACTION_CATEGORIES.items():
            ttk.Label(parent, text=cat, font=("TkDefaultFont", 10, "bold")).grid(row=row, column=0, sticky="w", pady=(8, 3), padx=6)
            row += 1
            for action in actions:
                btn = tk.Button(parent, text=action, font=("TkDefaultFont", 12, "bold"), height=2,
                                command=lambda a=action: self.select_action(a), wraplength=250)
                btn.grid(row=row, column=0, sticky="ew", padx=6, pady=3)
                row += 1

        ttk.Separator(parent, orient="horizontal").grid(row=row, column=0, sticky="ew", padx=6, pady=8)
        row += 1
        self.emergency_btn = tk.Button(parent, text="EMERGENCY STOP (Space)", bg="#c62828", fg="white", font=("TkDefaultFont", 13, "bold"),
                                       height=2, command=self.do_emergency_stop)
        self.emergency_btn.grid(row=row, column=0, sticky="ew", padx=6, pady=6)
        parent.columnconfigure(0, weight=1)

    def _build_center_panel(self, parent):
        for i in range(8):
            parent.rowconfigure(i, weight=0)
        parent.columnconfigure(0, weight=1)

        ttk.Label(parent, text="State:", font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w", padx=8, pady=(10, 3))
        self.state_label = ttk.Label(parent, textvariable=self.status_var, font=("TkDefaultFont", 14, "bold"), foreground="green")
        self.state_label.grid(row=1, column=0, sticky="w", padx=8)

        ttk.Label(parent, text="Selected action:", font=("TkDefaultFont", 10, "bold")).grid(row=2, column=0, sticky="w", padx=8, pady=(12, 3))
        ttk.Label(parent, textvariable=self.selected_action_var, wraplength=520).grid(row=3, column=0, sticky="w", padx=8)

        button_row = ttk.Frame(parent)
        button_row.grid(row=4, column=0, sticky="ew", padx=8, pady=8)
        button_row.columnconfigure((0, 1, 2), weight=1)
        ttk.Button(button_row, text="Confirm / Execute (Enter)", command=self.confirm_and_execute).grid(row=0, column=0, sticky="ew", padx=2)
        ttk.Button(button_row, text="Cancel Current", command=self.cancel_current).grid(row=0, column=1, sticky="ew", padx=2)
        ttk.Button(button_row, text="Inject Error", command=self.inject_error).grid(row=0, column=2, sticky="ew", padx=2)

        queue_frame = ttk.LabelFrame(parent, text="Queued / Current / Completed")
        queue_frame.grid(row=5, column=0, sticky="nsew", padx=8, pady=6)
        queue_frame.columnconfigure((0, 1, 2), weight=1)

        self.current_lbl = ttk.Label(queue_frame, text="Current: -", wraplength=180)
        self.current_lbl.grid(row=0, column=0, sticky="nw", padx=5, pady=4)
        self.queue_lbl = ttk.Label(queue_frame, text="Queue: -", wraplength=180)
        self.queue_lbl.grid(row=0, column=1, sticky="nw", padx=5, pady=4)
        self.completed_lbl = ttk.Label(queue_frame, text="Completed: -", wraplength=220)
        self.completed_lbl.grid(row=0, column=2, sticky="nw", padx=5, pady=4)

        safety_frame = ttk.Frame(parent)
        safety_frame.grid(row=6, column=0, sticky="ew", padx=8, pady=(8, 4))
        ttk.Button(safety_frame, text="Clear Queue", command=self.clear_queue).pack(side="left", padx=2)
        ttk.Button(safety_frame, text="Return to Safe Pose", command=lambda: self.select_action("Return to safe pose")).pack(side="left", padx=2)
        ttk.Button(safety_frame, text="Reset Robot State", command=self.reset_robot).pack(side="left", padx=2)

    def _build_right_panel(self, parent):
        parent.columnconfigure(0, weight=1)

        mode_frame = ttk.LabelFrame(parent, text="Mode")
        mode_frame.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        ttk.Radiobutton(mode_frame, text="Study", variable=self.mode_var, value="Study", command=self.on_mode_changed).pack(anchor="w", padx=4, pady=2)
        ttk.Radiobutton(mode_frame, text="Training", variable=self.mode_var, value="Training", command=self.on_mode_changed).pack(anchor="w", padx=4, pady=2)

        sc_frame = ttk.LabelFrame(parent, text="Scenarios")
        sc_frame.grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        names = [s.name for s in self.scenarios]
        combo = ttk.Combobox(sc_frame, values=names, textvariable=self.scenario_var, state="readonly")
        combo.pack(fill="x", padx=5, pady=4)
        combo.bind("<<ComboboxSelected>>", lambda e: self.load_scenario(self.scenario_var.get()))
        ttk.Button(sc_frame, text="Reload Scenario", command=lambda: self.load_scenario(self.scenario_var.get())).pack(fill="x", padx=5, pady=3)

        self.scenario_desc_lbl = ttk.Label(sc_frame, text="", wraplength=340, foreground="#333")
        self.scenario_desc_lbl.pack(fill="x", padx=5, pady=4)
        self.recommended_text = tk.Text(sc_frame, height=5, wrap="word", state="disabled")
        self.recommended_text.pack(fill="x", padx=5, pady=4)

        ctx = ttk.LabelFrame(parent, text="Context Parameters")
        ctx.grid(row=2, column=0, sticky="nsew", padx=6, pady=6)
        fields = {
            "target_person": ["Surgeon", "Nurse", "Lead Surgeon", "Resident"],
            "instrument_type": ["Forceps", "Scalpel", "Syringe", "Clamp", "Swab"],
            "urgency_level": ["Low", "Normal", "High", "Critical"],
            "side_direction": ["Left", "Right", "Center"],
            "speed_profile": ["Slow", "Standard", "Fast"],
        }
        for i, (name, options) in enumerate(fields.items()):
            ttk.Label(ctx, text=name.replace("_", " ").title()).grid(row=i, column=0, sticky="w", padx=4, pady=3)
            var = tk.StringVar(value=options[0])
            self.param_vars[name] = var
            cb = ttk.Combobox(ctx, values=options, textvariable=var, state="readonly")
            cb.grid(row=i, column=1, sticky="ew", padx=4, pady=3)
            cb.bind("<<ComboboxSelected>>", lambda e, n=name: self.on_param_change(n))
        ctx.columnconfigure(1, weight=1)

    def _build_bottom_panel(self, parent):
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(0, weight=1)
        self.log_text = tk.Text(parent, height=10, state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)
        controls = ttk.Frame(parent)
        controls.grid(row=1, column=0, sticky="ew", padx=5, pady=(0, 5))
        ttk.Button(controls, text="Export CSV", command=self.export_logs).pack(side="left")
        ttk.Button(controls, text="Clear Log View", command=self.clear_log_view).pack(side="left", padx=4)

    def _bind_shortcuts(self):
        self.bind("<Return>", lambda e: self.confirm_and_execute())
        self.bind("<space>", lambda e: self.do_emergency_stop())
        self.bind("1", lambda e: self.select_action("Handover item"))
        self.bind("2", lambda e: self.select_action("Approach operator"))
        self.bind("3", lambda e: self.select_action("Move to standby"))
        self.bind("4", lambda e: self.select_action("Return to safe pose"))
        self.bind("c", lambda e: self.cancel_current())

    def _current_mode(self) -> str:
        return self.mode_var.get()

    def _current_scenario(self) -> str:
        return self.scenario_var.get()

    def _get_context(self) -> ContextParameters:
        return ContextParameters(**{k: v.get() for k, v in self.param_vars.items()})

    def select_action(self, action: str):
        self.selected_action_var.set(action)
        self.logger_and_view("action_selected", f"Selected action: {action}")

    def confirm_and_execute(self):
        action = self.selected_action_var.get()
        if action == "No action selected":
            self.logger_and_view("warning", "Execute ignored: no action selected")
            return
        req = ActionRequest(action=action, params=self._get_context(), selected_at=time.time())
        self.robot.select_and_queue(req)
        self.robot.execute_next(self._current_scenario(), self._current_mode())

    def cancel_current(self):
        self.robot.cancel_current(self._current_scenario(), self._current_mode())

    def do_emergency_stop(self):
        self.robot.emergency_stop(self._current_scenario(), self._current_mode())

    def clear_queue(self):
        self.robot.clear_queue(self._current_scenario(), self._current_mode())

    def reset_robot(self):
        self.robot.reset(self._current_scenario(), self._current_mode())

    def inject_error(self):
        self.robot.set_error("Simulated fault condition for recovery drill", self._current_scenario(), self._current_mode())

    def on_mode_changed(self):
        self.logger_and_view("mode_changed", f"Mode changed to {self._current_mode()}")

    def on_param_change(self, name: str):
        self.logger_and_view("parameter_change", f"{name} -> {self.param_vars[name].get()}")

    def load_scenario(self, scenario_name: str, initial: bool = False):
        s = next((x for x in self.scenarios if x.name == scenario_name), None)
        if s is None:
            return
        for k, v in asdict(s.preload_params).items():
            if k in self.param_vars:
                self.param_vars[k].set(v)
        self.scenario_desc_lbl.configure(text=s.description)
        self.recommended_text.configure(state="normal")
        self.recommended_text.delete("1.0", "end")
        self.recommended_text.insert("1.0", "Recommended flow:\n- " + "\n- ".join(s.recommended_actions))
        self.recommended_text.configure(state="disabled")
        self.selected_action_var.set("No action selected")
        self.robot.clear_queue(self._current_scenario(), self._current_mode())
        self.robot.reset(self._current_scenario(), self._current_mode())
        self.logger_and_view("scenario_start" if initial else "scenario_switched", f"Scenario loaded: {s.name}")

    def logger_and_view(self, event_type: str, details: str):
        entry = self.logger.log(event_type, details, self._current_scenario(), self._current_mode())
        self._append_log(entry)

    def refresh_state(self):
        st = self.robot.state
        self.status_var.set(st)
        color = {"ready": "green", "executing": "blue", "paused": "#bb6d00", "error": "#b71c1c", "emergency stop": "#c62828", "idle": "gray"}.get(st, "black")
        self.state_label.configure(foreground=color)

        cur = self.robot.current_action.action if self.robot.current_action else "-"
        q = ", ".join(r.action for r in self.robot.queue) if self.robot.queue else "-"
        done = "\n".join(self.robot.completed[:6]) if self.robot.completed else "-"

        self.current_lbl.configure(text=f"Current: {cur}")
        self.queue_lbl.configure(text=f"Queue: {q}")
        self.completed_lbl.configure(text=f"Completed:\n{done}")

        if st in {"error", "emergency stop"}:
            self.selected_action_var.set("No action selected")

    def _append_log(self, entry: LogEntry):
        if self.log_text is None:
            return
        line = (
            f"[{entry.timestamp}] {entry.event_type} | {entry.details} | "
            f"lat={entry.latency_ms:.1f}ms dur={entry.duration_ms:.1f}ms | "
            f"scenario={entry.scenario} mode={entry.mode}\n"
        )
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def export_logs(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        self.logger.export_csv(path)
        messagebox.showinfo("Export", f"Logs exported to:\n{path}")

    def clear_log_view(self):
        if self.log_text is None:
            return
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")


if __name__ == "__main__":
    app = WoZApp()
    app.mainloop()
