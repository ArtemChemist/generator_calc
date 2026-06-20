import math
import numpy as np
from scipy.linalg import expm


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


def simulate_chain(
    lambdas: list[float],
    branching_ratios: list[float],
    N0_first: float,
    milking_interval_s: float,
    duration_s: float,
    n_points_per_interval: int = 200,
) -> dict:
    """
    Simulate an N-member linear decay chain with fixed-interval milking of the last species.

    Uses the matrix exponential of the ODE coefficient matrix — exact for any chain length,
    no degenerate-case handling required. Only the last species is harvested at each milking;
    all intermediates carry over.

    lambdas: decay constants [λ0, λ1, ..., λ_{N-1}] in s⁻¹
    branching_ratios: [br0, br1, ..., br_{N-2}] — br_i is the fraction of λ_i that feeds λ_{i+1}
    N0_first: initial atom count of the first (parent) species
    Returns: t_seconds, N_values (list of N arrays, one per species), milking_events
    """
    n = len(lambdas)

    # Tridiagonal ODE matrix: A[i,i] = -λi, A[i+1,i] = br_i * λ_i
    A = np.diag(-np.array(lambdas, dtype=float))
    for i in range(n - 1):
        A[i + 1, i] = branching_ratios[i] * lambdas[i]

    milking_times = np.arange(milking_interval_s, duration_s, milking_interval_s)
    segment_bounds = np.concatenate(([0.0], milking_times, [duration_s]))

    t_global = []
    N_global = [[] for _ in range(n)]
    milking_events = []

    N_seg = np.zeros(n)
    N_seg[0] = N0_first

    for i in range(len(segment_bounds) - 1):
        t_start = segment_bounds[i]
        t_end = segment_bounds[i + 1]
        local_t = np.linspace(0.0, t_end - t_start, n_points_per_interval)

        # Exact solution: N(t) = expm(A·t) @ N_seg
        N_at_t = np.stack([expm(A * t) @ N_seg for t in local_t])

        t_global.append(t_start + local_t)
        for k in range(n):
            N_global[k].append(N_at_t[:, k])

        is_milking = i < len(segment_bounds) - 2
        if is_milking:
            N_end = N_at_t[-1]
            yield_atoms = float(N_end[-1])
            milking_events.append((float(t_end), yield_atoms))
            N_seg = N_end.copy()
            N_seg[-1] = 0.0  # harvest last species; intermediates carry over
        else:
            N_seg = N_at_t[-1]

    return {
        't_seconds': np.concatenate(t_global),
        'N_values': [np.concatenate(N_global[k]) for k in range(n)],
        'milking_events': milking_events,
    }


def infer_duration_chain(
    lambdas: list[float],
    branching_ratios: list[float],
    N0_first: float,
    milking_interval_s: float,
    min_yield_atoms: float,
    max_duration_s: float = 10 * 365.25 * 24 * 3600,
) -> float | None:
    """
    Walk milking cycles for an N-member chain until the last species yield drops below min_yield_atoms.
    The transition matrix expm(A * milking_interval_s) is computed once and reused each cycle.
    Returns the time (s) of the first below-threshold event, or None if never reached.
    """
    n = len(lambdas)
    A = np.diag(-np.array(lambdas, dtype=float))
    for i in range(n - 1):
        A[i + 1, i] = branching_ratios[i] * lambdas[i]

    M = expm(A * milking_interval_s)  # transition matrix, computed once
    max_iter = int(max_duration_s / milking_interval_s)

    N_seg = np.zeros(n)
    N_seg[0] = N0_first

    for i in range(max_iter):
        N_end = M @ N_seg
        if N_end[-1] < min_yield_atoms:
            return (i + 1) * milking_interval_s
        N_seg = N_end.copy()
        N_seg[-1] = 0.0

    return None
