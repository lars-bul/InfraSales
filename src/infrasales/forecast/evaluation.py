"""How well a model ranks municipalities: the measures of a backtest.

All measures take labels (0 or 1) and scores of the same rows. Ranking measures matter most for
sales: does the list put the municipalities that did tender near the top?
"""

from collections.abc import Sequence


def roc_auc(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    """The chance a random positive outranks a random negative, ties half; None for one class."""
    positives = sum(labels)
    negatives = len(labels) - positives
    if positives == 0 or negatives == 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: scores[i])
    ranks = [0.0] * len(scores)
    start = 0
    while start < len(order):
        end = start
        while end + 1 < len(order) and scores[order[end + 1]] == scores[order[start]]:
            end += 1
        rank = (start + end) / 2 + 1  # tied scores share their mean rank
        for i in order[start : end + 1]:
            ranks[i] = rank
        start = end + 1
    positive_ranks = sum(rank for rank, label in zip(ranks, labels, strict=True) if label)
    return (positive_ranks - positives * (positives + 1) / 2) / (positives * negatives)


def average_precision(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    """The mean precision at each positive, down the list best first; None without positives."""
    positives = sum(labels)
    if positives == 0:
        return None
    ranked = sorted(zip(scores, labels, strict=True), key=lambda pair: pair[0], reverse=True)
    found = 0
    total = 0.0
    for position, (_, label) in enumerate(ranked, start=1):
        if label:
            found += 1
            total += found / position
    return total / positives


def precision_at(labels: Sequence[int], scores: Sequence[float], k: int) -> float | None:
    """Of the `k` best scored, the share that did tender; None for an empty list."""
    if not labels or k <= 0:
        return None
    ranked = sorted(zip(scores, labels, strict=True), key=lambda pair: pair[0], reverse=True)[:k]
    return sum(label for _, label in ranked) / len(ranked)


def brier(labels: Sequence[int], scores: Sequence[float]) -> float | None:
    """The mean squared gap between score and outcome: for probabilities; None for no rows."""
    if not labels:
        return None
    return sum((s - y) ** 2 for s, y in zip(scores, labels, strict=True)) / len(labels)
