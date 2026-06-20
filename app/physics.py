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
    milking_times = np.arange(milking_interval_s, duration_s, milking_interval_s)  # timestamps of each milking harvest
    segment_bounds = np.concatenate(([0.0], milking_times, [duration_s]))  # time boundaries between milking cycles, including t=0 and t=end

    t_global = []    # accumulated time points across all segments (seconds)
    N1_global = []   # accumulated parent atom counts across all segments
    N2_global = []   # accumulated daughter atom counts across all segments
    milking_events = []  # list of (time_s, yield_atoms) — one entry per harvest

    N1_seg = N1_0   # parent atom count at the start of the current segment
    N2_seg = 0.0    # daughter atom count at the start of the current segment (zero at t=0, reset to zero after each milking)
    dl = lambda2 - lambda1  # difference of decay constants; used in the Bateman denominator

    for i in range(len(segment_bounds) - 1):
        t_start = segment_bounds[i]    # absolute start time of this segment
        t_end = segment_bounds[i + 1]  # absolute end time of this segment (next milking or final time)
        local_t = np.linspace(0.0, t_end - t_start, n_points_per_interval)  # time axis relative to segment start

        exp1 = np.exp(-lambda1 * local_t)  # parent decay factor at each point
        exp2 = np.exp(-lambda2 * local_t)  # daughter decay factor at each point

        # N1(t) = N1_seg * e^(-λ1·t) — standard exponential decay from segment-start count
        N1 = N1_seg * exp1

        if abs(dl) < 1e-15 * max(lambda1, lambda2, 1e-30):
            # L'Hôpital limit of the Bateman equation when λ1 ≈ λ2:
            # N2(t) = br·λ1·N1_seg·t·e^(-λ1·t) + N2_seg·e^(-λ2·t)
            # The (e^-λ1t - e^-λ2t)/(λ2-λ1) term → t·e^-λt as λ1→λ2
            N2 = branching_ratio * lambda1 * N1_seg * local_t * exp1 + N2_seg * exp2
        else:
            # General Bateman equation for a two-member chain with initial daughter inventory:
            # N2(t) = br·λ1·N1_seg/(λ2-λ1) · (e^(-λ1·t) - e^(-λ2·t))  ← ingrowth from parent
            #       + N2_seg · e^(-λ2·t)                                  ← decay of existing daughter
            N2 = (branching_ratio * lambda1 * N1_seg / dl) * (exp1 - exp2) + N2_seg * exp2

        # shift local_t back to absolute time and accumulate into global arrays
        t_global.append(t_start + local_t)
        N1_global.append(N1)
        N2_global.append(N2)

        is_milking = i < len(segment_bounds) - 2  # True for every segment except the last (which ends at duration_s, not a milking)
        if is_milking:
            yield_atoms = float(N2[-1])  # daughter atoms present at the end of this segment — harvested by milking
            milking_events.append((float(t_end), yield_atoms))
            N1_seg = float(N1[-1])   # parent carries over; it is not removed during milking
            N2_seg = 0.0             # daughter is fully eluted; next segment starts from zero
        else:
            # final segment: no milking, just carry both populations forward for the plots
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
