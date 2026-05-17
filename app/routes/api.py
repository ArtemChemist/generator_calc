import math
from flask import Blueprint, jsonify, request
from ..db import get_db
from ..physics import simulate_generator, activity_from_atoms

bp = Blueprint('api', __name__)

LN2 = math.log(2)


def _half_life_row(symbol, db):
    row = db.execute('SELECT half_life_s FROM isotopes WHERE symbol = ?', (symbol,)).fetchone()
    return row['half_life_s'] if row else None


@bp.route('/presets')
def presets():
    db = get_db()
    rows = db.execute('''
        SELECT p.id, p.display_name, p.parent_symbol, p.daughter_symbol,
               i1.half_life_s AS parent_half_life_s,
               i2.half_life_s AS daughter_half_life_s
        FROM generator_presets p
        JOIN isotopes i1 ON i1.symbol = p.parent_symbol
        JOIN isotopes i2 ON i2.symbol = p.daughter_symbol
        ORDER BY p.sort_order
    ''').fetchall()
    return jsonify([dict(r) for r in rows])


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

    try:
        initial_activity_MBq = float(body['initial_activity_MBq'])
        milking_interval_h = float(body['milking_interval_h'])
        duration_h = float(body['duration_h'])
        min_yield_MBq = float(body.get('min_yield_MBq', 0))
    except (KeyError, TypeError, ValueError) as e:
        return jsonify({'error': f'Invalid parameter: {e}'}), 400

    if initial_activity_MBq <= 0:
        return jsonify({'error': 'initial_activity_MBq must be > 0'}), 400
    if milking_interval_h <= 0:
        return jsonify({'error': 'milking_interval_h must be > 0'}), 400
    if duration_h <= milking_interval_h:
        return jsonify({'error': 'duration_h must be greater than milking_interval_h'}), 400
    if duration_h > 8760:
        return jsonify({'error': 'duration_h must be <= 8760 (1 year)'}), 400

    db = get_db()
    hl_parent = _half_life_row(parent_symbol, db)
    hl_daughter = _half_life_row(daughter_symbol, db)
    if hl_parent is None:
        return jsonify({'error': f'Unknown isotope: {parent_symbol}'}), 400
    if hl_daughter is None:
        return jsonify({'error': f'Unknown isotope: {daughter_symbol}'}), 400
    if hl_parent <= 0 or hl_parent >= 1e29:
        return jsonify({'error': f'{parent_symbol} is stable; cannot be a generator parent'}), 400

    dm = db.execute(
        'SELECT branching_ratio FROM decay_modes WHERE parent_symbol=? AND daughter_symbol=?',
        (parent_symbol, daughter_symbol),
    ).fetchone()
    branching_ratio = dm['branching_ratio'] if dm else 1.0

    lambda1 = LN2 / hl_parent
    lambda2 = LN2 / hl_daughter if hl_daughter < 1e29 else 0.0

    N1_0 = (initial_activity_MBq * 1e6) / lambda1

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
        {
            'time_h': t_s / 3600,
            'yield_MBq': round(lambda2 * atoms / 1e6, 4),
        }
        for t_s, atoms in result['milking_events']
    ]

    return jsonify({
        'time_points_h': t_h,
        'parent_activity_MBq': parent_mbq,
        'daughter_activity_MBq': daughter_mbq,
        'milking_events': milking_events,
        'min_yield_MBq': min_yield_MBq,
        'metadata': {
            'parent_symbol': parent_symbol,
            'daughter_symbol': daughter_symbol,
            'parent_half_life_h': round(hl_parent / 3600, 4),
            'daughter_half_life_h': round(hl_daughter / 3600, 4),
            'branching_ratio': branching_ratio,
        },
    })
