# WoZ Medical Assistive Arm Control Interface (Prototype)

## Purpose
This project is a **Wizard-of-Oz (WoZ) desktop prototype** for early research studies around a future medical assistive robotic arm.
It focuses on the **wizard/operator interface** (fast action triggering, explicit manual control, recovery operations, and study logging), not on robot autonomy.

## What this prototype is
- A Python 3.11 + Tkinter desktop app.
- A simulated control interface for wizard-side operation.
- A research/demo tool with scenario handling, context parameters, and event logging.

## What this prototype is NOT
- Not a final clinical product.
- Not connected to a real robot.
- No speech recognition/synthesis.
- No motion planning/control backend.

## Run
```bash
python3 main.py
```

## UI layout
- **Left panel (Live Control):**
  - Large quick action buttons grouped by category.
  - Always-visible emergency stop button.
- **Center panel (Robot State & Execution):**
  - Current simulated robot state (`ready`, `executing`, `error`, `emergency stop`, etc.).
  - Selected action, queue, current action, and recent completed actions.
  - Confirm/execute, cancel current, inject error, clear queue, return-safe, and reset actions.
- **Right panel (Scenario + Context + Mode):**
  - Study vs Training mode.
  - Scenario selection/reload with 3 demo scenarios:
    1. Simple handover
    2. Interrupted handover
    3. Urgent reprioritization
  - Context parameters (target person, instrument type, urgency, side/direction, speed profile).
- **Bottom panel (Logs):**
  - Timestamped event stream.
  - Export logs to CSV.

## Keyboard shortcuts
- `Enter`: confirm/execute selected action
- `Space`: emergency stop
- `1`: handover item
- `2`: approach operator
- `3`: move to standby
- `4`: return to safe pose
- `c`: cancel current action

## Simulation details
The app simulates a robot state machine with transitions and timed action execution:
- States: `idle`, `ready`, `executing`, `paused`, `error`, `emergency stop`
- Action durations are synthetic and depend on action + urgency + speed profile.
- Logs include:
  - scenario start/switch
  - action selection
  - parameter changes
  - action execution/completion
  - cancellation
  - error
  - emergency stop
  - queue/state reset events
- For execution events, a simulated **latency** (selection→execution) and **duration** are recorded.

## Extension path to real robot backend
This prototype keeps simulation logic separate from UI logic via `RobotSimulator` + dataclasses.
A next step could replace timer-driven simulation with backend calls:
1. Keep UI and event logging as-is.
2. Replace `RobotSimulator.execute_next()` internals with command dispatch to middleware/API.
3. Map backend status callbacks into `refresh_state()` updates.
4. Preserve the same action/context schema for study continuity.

## File overview
- `main.py`: complete application (UI, scenarios, simulated state machine, logging/export).
- `README.md`: usage and design overview.
