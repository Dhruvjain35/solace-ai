import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// Lazy-loaded chunk (DEPS-006): recharts is heavy, so this whole module is
// imported via React.lazy from TrustReport and never enters the main bundle.

export interface CoveragePoint {
  esi: string;
  coverage: number;
}

interface CoverageChartProps {
  data: CoveragePoint[];
  target: number | null;
}

function CoverageChart({ data, target }: CoverageChartProps) {
  return (
    <div role="img" aria-label="Empirical conformal coverage by ESI level on the synthetic validation cohort">
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} margin={{ top: 24, right: 12, left: 0, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(74,85,87,0.15)" vertical={false} />
          <XAxis
            dataKey="esi"
            tickFormatter={(v) => `ESI ${v}`}
            tick={{ fill: "#4A5557", fontSize: 12 }}
            axisLine={{ stroke: "rgba(74,85,87,0.2)" }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 1]}
            tickFormatter={(v) => `${Math.round(v * 100)}%`}
            tick={{ fill: "#4A5557", fontSize: 12 }}
            axisLine={false}
            tickLine={false}
            width={44}
          />
          <Tooltip
            formatter={(v: number) => [`${(v * 100).toFixed(1)}%`, "Coverage"]}
            labelFormatter={(l) => `ESI ${l}`}
            contentStyle={{
              borderRadius: 6,
              border: "1px solid rgba(74,85,87,0.2)",
              fontSize: 12,
            }}
          />
          {target !== null && (
            <ReferenceLine
              y={target}
              stroke="#B05436"
              strokeDasharray="4 4"
              label={{
                value: `Target ${Math.round(target * 100)}%`,
                position: "right",
                fill: "#B05436",
                fontSize: 11,
              }}
            />
          )}
          <Bar dataKey="coverage" radius={[4, 4, 0, 0]} maxBarSize={56}>
            {data.map((d) => (
              <Cell
                key={d.esi}
                fill={target !== null && d.coverage >= target ? "#557D6E" : "#B05436"}
              />
            ))}
            <LabelList
              dataKey="coverage"
              position="top"
              formatter={(v: number) => `${Math.round(v * 100)}%`}
              fill="#1A2023"
              fontSize={11}
            />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

CoverageChart.displayName = "CoverageChart";

export default CoverageChart;
