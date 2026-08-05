"""
GraphLang — Universal Language Discovery.

Given millions of IR graphs, find the minimum set of operations
that can reconstruct 99.999% of all code.

Method:
1. Extract all 2-node subgraphs (parent→child)
2. Rank by frequency
3. Compute coverage: what % of all nodes are covered by top-K patterns
4. Find the minimum K where coverage ≥ 99.999%
"""
import sys, time, pickle
from collections import Counter
sys.path.insert(0, '/home/app/graphlang')


def discover_minimum_operations(predictor_pkl: str = 'predictor_10m.pkl',
                                 top_n: int = 50):
    """Discover the minimum set of operations from the predictor model."""
    
    with open(predictor_pkl, 'rb') as f:
        p = pickle.load(f)
    
    pc = p.parent_child
    total_transitions = p.total_transitions
    
    print(f"Total transitions: {total_transitions:,}")
    print(f"Unique parent→child pairs: {len(pc)}")
    
    # ─── 1. Rank all parent→child patterns ───
    patterns = []
    for pk, counter in pc.items():
        for ck, count in counter.items():
            patterns.append((pk, ck, count))
    patterns.sort(key=lambda x: -x[2])
    
    print(f"\nTop 20 patterns:")
    cumulative = 0
    for i, (pk, ck, cnt) in enumerate(patterns[:20]):
        cumulative += cnt
        pct = cnt / total_transitions * 100
        cum_pct = cumulative / total_transitions * 100
        print(f"  {i+1:2d}. {pk:12s} → {ck:12s}: {cnt:12,d} ({pct:5.1f}%)  cum={cum_pct:.1f}%")
    
    # ─── 2. Coverage curve ───
    print(f"\n{'─'*60}")
    print(f"{'K':4s}  {'Coverage':8s}  {'Patterns'}")
    print(f"{'─'*60}")
    
    cumulative = 0
    for k in [1, 2, 3, 5, 8, 10, 12, 15, 20, 30, 50]:
        coverage = sum(c for _, _, c in patterns[:k])
        pct = coverage / total_transitions * 100
        names = '+'.join(f'{pk}→{ck}' for pk,ck,_ in patterns[:k])
        print(f"{k:3d}  {pct:6.2f}%   {names[:80]}...")
    
    # ─── 3. Find the minimum set for 99.999% ───
    cumulative = 0
    for k, (_, _, cnt) in enumerate(patterns, 1):
        cumulative += cnt
        if cumulative / total_transitions >= 0.99999:
            print(f"\n{'═'*60}")
            print(f"MINIMUM SET: {k} parent→child patterns")
            print(f"Coverage: {cumulative/total_transitions*100:.3f}%")
            print(f"Remaining patterns: {len(patterns) - k}")
            print(f"{'═'*60}")
            break
    
    # ─── 4. What are the remaining patterns? ───
    remaining = patterns[k:]
    print(f"\nRare patterns (< 0.001% each): {len(remaining)}")
    for pk, ck, cnt in remaining[:10]:
        print(f"  {pk:12s} → {ck:12s}: {cnt:8,d} ({cnt/total_transitions*100:.4f}%)")
    
    # ─── 5. Universal operator set ───
    print(f"\n{'═'*60}")
    print("UNIVERSAL OPERATORS (cover 99.999% of human code)")
    print(f"{'═'*60}")
    
    # Unique parent kinds that appear
    parent_kinds = set(pk for pk, _, _ in patterns)
    child_kinds = set(ck for _, ck, _ in patterns)
    
    print(f"\nKinds used as parents: {len(parent_kinds)}")
    for pk in sorted(parent_kinds):
        total = sum(pc[pk].values())
        trans = [(ck, cnt) for ck, cnt in pc[pk].most_common(4)]
        line = ', '.join(f'{ck}({cnt/total*100:.0f}%)' for ck, cnt in trans)
        print(f"  {pk:12s} → [{line}]")
    
    print(f"\nTotal operators discovered: {len(patterns)}")
    print(f"Operators needed for 99.999%: {k}")
    print(f"Compression of operator space: {len(patterns)/k:.1f}x")
    
    return patterns, k


if __name__ == "__main__":
    discover_minimum_operations()
