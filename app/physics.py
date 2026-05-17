import math
import numpy as np


def simulate_generator(
    lambda1: float,
    lambda2: float,
    branching_ratio: float,
    N1_0: float,
    milking_interval_s: float,
    duration_s: float,
    n_points_per_interval: int = 200,
) -> dict:
    """
    Analytic Bateman simulation of a parent→daughter generator with fixed-interval milking.

    All inputs in SI units (seconds, atom counts).
    Returns atom counts; caller converts to activity.
    """
    milking_times = np.arange(milking_interval_s, duration_s, milking_interval_s)
    segment_bounds = np.concatenate(([0.0], milking_times, [duration_s]))

    t_global = []
    N1_global = []
    N2_global = []
    milking_events = []  # list of (time_s, yield_atoms)

    N1_seg = N1_0
    N2_seg = 0.0
    dl = lambda2 - lambda1

    for i in range(len(segment_bounds) - 1):
        t_start = segment_bounds[i]
        t_end = segment_bounds[i + 1]
        local_t = np.linspace(0.0, t_end - t_start, n_points_per_interval)

        exp1 = np.exp(-lambda1 * local_t)
        exp2 = np.exp(-lambda2 * local_t)

        N1 = N1_seg * exp1

        if abs(dl) < 1e-15 * max(lambda1, lambda2, 1e-30):
            # L'Hopital limit when λ1 ≈ λ2
            N2 = branching_ratio * lambda1 * N1_seg * local_t * exp1 + N2_seg * exp2
        else:
            N2 = (branching_ratio * lambda1 * N1_seg / dl) * (exp1 - exp2) + N2_seg * exp2

        t_global.append(t_start + local_t)
        N1_global.append(N1)
        N2_global.append(N2)

        is_milking = i < len(segment_bounds) - 2
        if is_milking:
            yield_atoms = float(N2[-1])
            milking_events.append((float(t_end), yield_atoms))
            N1_seg = float(N1[-1])
            N2_seg = 0.0
        else:
            N1_seg = float(N1[-1])
            N2_seg = float(N2[-1])

    return {
        't_seconds': np.concatenate(t_global),
        'N1_values': np.concatenate(N1_global),
        'N2_values': np.concatenate(N2_global),
        'milking_events': milking_events,
    }


def infer_duration(
    lambda1: float,
    lambda2: float,
    branching_ratio: float,
    N1_0: float,
    milking_interval_s: float,
    min_yield_atoms: float,
    max_duration_s: float = 10 * 365.25 * 24 * 3600,
) -> float | None:
    """
    Walk milking cycles until yield drops below min_yield_atoms.
    Returns the time (s) of the first below-threshold event, or None if never reached.
    """
    max_iter = int(max_duration_s / milking_interval_s)
    N1_seg = N1_0
    N2_seg = 0.0
    dl = lambda2 - lambda1

    for i in range(max_iter):
        exp1 = math.exp(-lambda1 * milking_interval_s)
        exp2 = math.exp(-lambda2 * milking_interval_s)

        if abs(dl) < 1e-15 * max(lambda1, lambda2, 1e-30):
            N2_end = branching_ratio * lambda1 * N1_seg * milking_interval_s * exp1 + N2_seg * exp2
        else:
            N2_end = (branching_ratio * lambda1 * N1_seg / dl) * (exp1 - exp2) + N2_seg * exp2

        t_event = (i + 1) * milking_interval_s
        if N2_end < min_yield_atoms:
            return t_event  # include this first below-threshold event as the endpoint

        N1_seg *= exp1
        N2_seg = 0.0

    return None


def activity_from_atoms(N: np.ndarray, decay_lambda: float) -> np.ndarray:
    return decay_lambda * N / 1e6  # → MBq
