#!/usr/bin/env python3
"""Plot named structures' channel profiles, each in its own colour.

cluster_tunnels.py colours by cluster, so every member of a cluster is drawn in
the same colour and individual structures cannot be told apart. This plots a
chosen set of structures with a distinct colour and a legend entry each — the
usual case being "show me the reference enzymes side by side".

    python3 plot_profiles.py --results-dir <run>/results \\
        5FUJ_heme 5OXU_heme 9HE9_heme grogu_heme -o refs.png

With no stems given it plots every structure that has a kept tunnel, which is
only readable for small sets.
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cluster_tunnels import load_tunnel, load_best_kept_tunnels  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('stems', nargs='*', help='structure stems to plot')
    p.add_argument('--results-dir', type=Path, required=True)
    p.add_argument('-o', '--out', type=Path, default=Path('profiles.png'))
    p.add_argument('--n-points', type=int, default=100)
    p.add_argument('--ylim', type=float, default=5)
    p.add_argument('--raw-distance', action='store_true',
                   help='x axis in angstrom instead of normalised 0-1')
    args = p.parse_args()

    best = load_best_kept_tunnels(args.results_dir / 'tunnel_selection.csv')
    if not best:
        sys.exit(f'No kept tunnels found in {args.results_dir}/tunnel_selection.csv')

    stems = args.stems or sorted(best)
    missing = [s for s in stems if s not in best]
    for s in missing:
        print(f'  [skip] {s}: no kept tunnel', file=sys.stderr)
    stems = [s for s in stems if s in best]
    if not stems:
        sys.exit('None of the requested structures have a kept tunnel.')

    cmap = plt.get_cmap('tab10' if len(stems) <= 10 else 'tab20')
    fig, ax = plt.subplots(figsize=(8, 5))

    for i, stem in enumerate(stems):
        res = load_tunnel(args.results_dir, stem, best[stem])
        if res is None:
            print(f'  [skip] {stem}: no profile data', file=sys.stderr)
            continue
        r, dist, length = res
        x = dist if args.raw_distance else dist / dist[-1]
        c = cmap(i % cmap.N)
        ax.plot(x,  r, color=c, linewidth=1.8,
                label=f'{stem}  (tunnel {best[stem]}, {length:.1f} A)')
        ax.plot(x, -r, color=c, linewidth=1.8)

    ax.axhline(0, color='black', linewidth=0.5, linestyle='--')
    ax.set_ylim(-args.ylim, args.ylim)
    ax.set_xlabel('Distance along tunnel (A)' if args.raw_distance
                  else 'Normalized distance (0 = heme, 1 = exit)')
    ax.set_ylabel('R (A)')
    ax.set_title('Channel profile per structure')
    ax.legend(fontsize=8, loc='upper left')
    fig.tight_layout()
    fig.savefig(args.out, dpi=150, bbox_inches='tight')
    print(f'Saved {args.out}')


if __name__ == '__main__':
    main()
