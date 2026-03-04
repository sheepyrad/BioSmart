import type { BoltzMetricInputRow, BoltzMetricSeries } from './types';

const DEFAULT_THRESHOLDS = [0.5, 0.6, 0.7, 0.8];

function scoreFn(affinity: number, probability: number) {
  return ((-affinity + 2.0) / 4.0) * probability;
}

export function computeBoltzMetrics(
  rows: BoltzMetricInputRow[],
  thresholds: number[] = DEFAULT_THRESHOLDS
): BoltzMetricSeries {
  const validRows = rows.filter(
    (row) =>
      row.affinityModel1 !== null &&
      row.probabilityModel1 !== null &&
      Number.isFinite(row.affinityModel1) &&
      Number.isFinite(row.probabilityModel1)
  ) as Array<BoltzMetricInputRow & { affinityModel1: number; probabilityModel1: number }>;

  const bestProb: number[] = new Array(validRows.length);
  const top10AvgProb: number[] = new Array(validRows.length);
  const top100AvgProb: number[] = new Array(validRows.length);
  const thresholdCounts: Record<string, number[]> = {};

  for (const t of thresholds) {
    thresholdCounts[t.toFixed(1)] = new Array(validRows.length).fill(0);
  }

  let bestScore = Number.NEGATIVE_INFINITY;
  let bestProbability = 0;

  const top10: Array<{ score: number; probability: number }> = [];
  const top100: Array<{ score: number; probability: number }> = [];

  const thresholdTotals = new Map<number, number>(thresholds.map((t) => [t, 0]));

  for (let i = 0; i < validRows.length; i += 1) {
    const row = validRows[i]!;
    const score = scoreFn(row.affinityModel1, row.probabilityModel1);
    const probability = row.probabilityModel1;

    if (score > bestScore) {
      bestScore = score;
      bestProbability = probability;
    }
    bestProb[i] = bestProbability;

    insertTopK(top10, { score, probability }, 10);
    top10AvgProb[i] =
      top10.length > 0
        ? top10.reduce((sum, item) => sum + item.probability, 0) / top10.length
        : 0;

    insertTopK(top100, { score, probability }, 100);
    top100AvgProb[i] =
      top100.length > 0
        ? top100.reduce((sum, item) => sum + item.probability, 0) / top100.length
        : 0;

    for (const threshold of thresholds) {
      if (probability > threshold) {
        thresholdTotals.set(threshold, (thresholdTotals.get(threshold) ?? 0) + 1);
      }
      thresholdCounts[threshold.toFixed(1)]![i] = thresholdTotals.get(threshold) ?? 0;
    }
  }

  return {
    pointCount: validRows.length,
    bestProb,
    top10AvgProb,
    top100AvgProb,
    thresholdCounts,
    thresholds,
  };
}

function insertTopK(
  target: Array<{ score: number; probability: number }>,
  item: { score: number; probability: number },
  k: number
) {
  if (target.length === 0) {
    target.push(item);
    return;
  }

  let insertAt = target.findIndex((entry) => item.score < entry.score);
  if (insertAt === -1) insertAt = target.length;
  target.splice(insertAt, 0, item);

  if (target.length > k) {
    target.shift();
  }
}
