import json
import math
from flask import Blueprint, jsonify, request
from ..db import get_db
from ..physics import simulate_generator, activity_from_atoms, infer_duration, simulate_chain, infer_duration_chain

bp = Blueprint('api', __name__)

LN2 = math.log(2)


def _half_life_row(symbol, db):
    row = db.execute('SELECT half_life_s FROM isotopes WHERE symbol = ?', (symbol,)).fetchone()
    return row['half_life_s'] if row else None


@bp.route('/presets')
def presets():
    db = get_db()
    rows = db.execute('''
        SELECT p.id, p.display_name, p.parent_symbol, p.intermediate_symbols,
               p.daughter_symbol,
               i1.half_life_s AS parent_half_life_s,
               i2.half_life_s AS daughter_half_life_s
        FROM generator_presets p
        JOIN isotopes i1 ON i1.symbol = p.parent_symbol
        JOIN isotopes i2 ON i2.symbol = p.daughter_symbol
        ORDER BY p.sort_order
    ''').fetchall()
    result = []
    for r in rows:
        item = dict(r)
        syms = json.loads(r['intermediate_symbols']) if r['intermediate_symbols'] else []
        item['intermediate_symbols'] = syms
        item['intermediate_half_lives_s'] = [_half_life_row(s, db) for s in syms]
        result.append(item)
    return jsonify(result)


@bp.route('/isotopes/search')
def isotopes_search():
    q = request.args.get('q', '').strip()
    if len(q) < 1:
        return jsonify([])
    db = get_db()
    pattern = f'%{q}%'
    rows = db.execute(
        'SELECT symbol, name, half_life_s FROM isotopes WHERE symbol LIKE ? OR name LIKE ? LIMIT 20',
        (pattern, pattern),
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route('/isotopes/<symbol>/daughters')
def isotope_daughters(symbol):
    db = get_db()
    rows = db.execute('''
        SELECT d.daughter_symbol, d.branching_ratio, d.mode,
               i.half_life_s AS daughter_half_life_s
        FROM decay_modes d
        JOIN isotopes i ON i.symbol = d.daughter_symbol
        WHERE d.parent_symbol = ?
        ORDER BY d.branching_ratio DESC
    ''', (symbol,)).fetchall()
    return jsonify([dict(r) for r in rows])


@bp.route('/calculate', methods=['POST'])
def calculate():
    body = request.get_json(force=True)

    parent_symbol = body.get('parent_symbol', '').strip()
    daughter_symbol = body.get('daughter_symbol', '').strip()
    intermediate_symbols = [s.strip() for s in (body.get('intermediate_symbols') or [])]

    try:
        initial_activity_MBq = float(body['initial_activity_MBq'])
        milking_interval_h = float(body['milking_interval_h'])
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({'error': f'Invalid parameter: {e}'}), 400

    raw_duration = body.get('duration_h')
    raw_min_yield = body.get('min_yield_MBq')
    try:
        duration_h = float(raw_duration) if raw_duration not in (None, '') else None
        min_yield_MBq = float(raw_min_yield) if raw_min_yield not in (None, '') else None
    except (TypeError, ValueError) as e:
        return jsonify({'error': f'Invalid parameter: {e}'}), 400

    if duration_h is None and not min_yield_MBq:
        return jsonify({'error': 'Provide duration, min yield threshold, or both.'}), 400
    if initial_activity_MBq <= 0:
        return jsonify({'error': 'initial_activity_MBq must be > 0'}), 400
    if milking_interval_h <= 0:
        return jsonify({'error': 'milking_interval_h must be > 0'}), 400
    if duration_h is not None:
        if duration_h <= milking_interval_h:
            return jsonify({'error': 'duration_h must be greater than milking_interval_h'}), 400
        if duration_h / milking_interval_h > 2000:
            return jsonify({'error': 'Simulation would exceed 2000 milking events. Increase the milking interval or reduce the duration.'}), 400

    db = get_db()
    hl_parent = _half_life_row(parent_symbol, db)
    hl_daughter = _half_life_row(daughter_symbol, db)
    if hl_parent is None:
        return jsonify({'error': f'Unknown isotope: {parent_symbol}'}), 400
    if hl_daughter is None:
        return jsonify({'error': f'Unknown isotope: {daughter_symbol}'}), 400
    if hl_parent <= 0 or hl_parent >= 1e29:
        return jsonify({'error': f'{parent_symbol} is stable; cannot be a generator parent'}), 400

    if not intermediate_symbols:
        # ── 2-member path (unchanged) ──────────────────────────────────────
        dm = db.execute(
            'SELECT branching_ratio FROM decay_modes WHERE parent_symbol=? AND daughter_symbol=?',
            (parent_symbol, daughter_symbol),
        ).fetchone()
        branching_ratio = dm['branching_ratio'] if dm else 1.0

        lambda1 = LN2 / hl_parent
        lambda2 = LN2 / hl_daughter if hl_daughter < 1e29 else 0.0
        N1_0 = (initial_activity_MBq * 1e6) / lambda1

        inferred_duration_h = None
        if duration_h is None:
            min_yield_atoms = (min_yield_MBq * 1e6) / lambda2 if lambda2 > 0 else 0
            duration_s = infer_duration(
                lambda1=lambda1,
                lambda2=lambda2,
                branching_ratio=branching_ratio,
                N1_0=N1_0,
                milking_interval_s=milking_interval_h * 3600,
                min_yield_atoms=min_yield_atoms,
            )
            if duration_s is None:
                return jsonify({'error': 'Yield stays above threshold for >10 years; specify a duration instead.'}), 400
            inferred_duration_h = round(duration_s / 3600, 4)
            duration_h = inferred_duration_h

        result = simulate_generator(
            lambda1=lambda1,
            lambda2=lambda2,
            branching_ratio=branching_ratio,
            N1_0=N1_0,
            milking_interval_s=milking_interval_h * 3600,
            duration_s=duration_h * 3600,
        )

        t_h = (result['t_seconds'] / 3600).tolist()
        parent_mbq = activity_from_atoms(result['N1_values'], lambda1).tolist()
        daughter_mbq = activity_from_atoms(result['N2_values'], lambda2).tolist()

        milking_events = [
            {'time_h': t_s / 3600, 'yield_MBq': round(lambda2 * atoms / 1e6, 4)}
            for t_s, atoms in result['milking_events']
        ]

        return jsonify({
            'time_points_h': t_h,
            'parent_activity_MBq': parent_mbq,
            'daughter_activity_MBq': daughter_mbq,
            'milking_events': milking_events,
            'min_yield_MBq': min_yield_MBq or 0,
            'inferred_duration_h': inferred_duration_h,
            'metadata': {
                'parent_symbol': parent_symbol,
                'daughter_symbol': daughter_symbol,
                'parent_half_life_h': round(hl_parent / 3600, 4),
                'daughter_half_life_h': round(hl_daughter / 3600, 4),
                'branching_ratio': branching_ratio,
            },
        })

    # ── N-member chain path ────────────────────────────────────────────────
    hl_intermediates = []
    for sym in intermediate_symbols:
        hl = _half_life_row(sym, db)
        if hl is None:
            return jsonify({'error': f'Unknown isotope: {sym}'}), 400
        hl_intermediates.append(hl)

    chain_symbols = [parent_symbol] + intermediate_symbols + [daughter_symbol]
    chain_hl_s = [hl_parent] + hl_intermediates + [hl_daughter]
    lambdas = [LN2 / hl if hl < 1e29 else 0.0 for hl in chain_hl_s]

    chain_brs = []
    for i in range(len(chain_symbols) - 1):
        dm = db.execute(
            'SELECT branching_ratio FROM decay_modes WHERE parent_symbol=? AND daughter_symbol=?',
            (chain_symbols[i], chain_symbols[i + 1]),
        ).fetchone()
        chain_brs.append(dm['branching_ratio'] if dm else 1.0)

    N0_first = (initial_activity_MBq * 1e6) / lambdas[0]
    lambda_daughter = lambdas[-1]

    inferred_duration_h = None
    if duration_h is None:
        min_yield_atoms = (min_yield_MBq * 1e6) / lambda_daughter if lambda_daughter > 0 else 0
        duration_s = infer_duration_chain(
            lambdas=lambdas,
            branching_ratios=chain_brs,
            N0_first=N0_first,
            milking_interval_s=milking_interval_h * 3600,
            min_yield_atoms=min_yield_atoms,
        )
        if duration_s is None:
            return jsonify({'error': 'Yield stays above threshold for >10 years; specify a duration instead.'}), 400
        inferred_duration_h = round(duration_s / 3600, 4)
        duration_h = inferred_duration_h

    result = simulate_chain(
        lambdas=lambdas,
        branching_ratios=chain_brs,
        N0_first=N0_first,
        milking_interval_s=milking_interval_h * 3600,
        duration_s=duration_h * 3600,
    )

    t_h = (result['t_seconds'] / 3600).tolist()
    N_activities = [activity_from_atoms(result['N_values'][k], lambdas[k]).tolist() for k in range(len(chain_symbols))]

    milking_events = [
        {'time_h': t_s / 3600, 'yield_MBq': round(lambda_daughter * atoms / 1e6, 4)}
        for t_s, atoms in result['milking_events']
    ]

    return jsonify({
        'time_points_h': t_h,
        'parent_activity_MBq': N_activities[0],           # backward compat
        'daughter_activity_MBq': N_activities[-1],        # backward compat
        'intermediate_activities_MBq': N_activities[1:-1],
        'milking_events': milking_events,
        'min_yield_MBq': min_yield_MBq or 0,
        'inferred_duration_h': inferred_duration_h,
        'metadata': {
            'chain_symbols': chain_symbols,
            'chain_half_lives_h': [round(hl / 3600, 4) for hl in chain_hl_s],
            'branching_ratios': chain_brs,
            # backward compat aliases
            'parent_symbol': parent_symbol,
            'daughter_symbol': daughter_symbol,
            'parent_half_life_h': round(hl_parent / 3600, 4),
            'daughter_half_life_h': round(hl_daughter / 3600, 4),
            'branching_ratio': chain_brs[-1],
        },
    })
