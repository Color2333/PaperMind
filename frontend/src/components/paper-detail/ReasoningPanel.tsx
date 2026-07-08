import {
  Zap,
  Target,
  TrendingUp,
  Brain,
  FlaskConical,
  Microscope,
  ThumbsUp,
  ThumbsDown,
  AlertTriangle,
  CheckCircle2,
  Lightbulb,
  Sparkles,
} from "lucide-react";
import type { ReasoningChainResult } from "@/types";
import ScoreCard from "./ScoreCard";
import ChainItem from "./ChainItem";
import ReasoningStepCard from "./ReasoningStepCard";

/* ================================================================
 * 推理链面板
 * ================================================================ */

function ReasoningPanel({ reasoning }: { reasoning: ReasoningChainResult }) {
  const steps = reasoning.reasoning_steps ?? [];
  const mc = reasoning.method_chain ?? ({} as Record<string, string>);
  const ec = reasoning.experiment_chain ?? ({} as Record<string, string>);
  const ia = reasoning.impact_assessment ?? ({} as Record<string, unknown>);

  const novelty = (ia.novelty_score as number) ?? 0;
  const rigor = (ia.rigor_score as number) ?? 0;
  const impact = (ia.impact_score as number) ?? 0;
  const overall = (ia.overall_assessment as string) ?? "";
  const strengths = (ia.strengths as string[]) ?? [];
  const weaknesses = (ia.weaknesses as string[]) ?? [];
  const suggestions = (ia.future_suggestions as string[]) ?? [];

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-3 gap-4">
        <ScoreCard
          label="创新性"
          score={novelty}
          icon={<Zap className="h-4 w-4" />}
          color="text-purple-500"
          bg="bg-purple-500/10"
        />
        <ScoreCard
          label="严谨性"
          score={rigor}
          icon={<Target className="h-4 w-4" />}
          color="text-blue-500"
          bg="bg-blue-500/10"
        />
        <ScoreCard
          label="影响力"
          score={impact}
          icon={<TrendingUp className="h-4 w-4" />}
          color="text-orange-500"
          bg="bg-orange-500/10"
        />
      </div>

      {overall && (
        <div className="bg-page dark:bg-page/50 rounded-xl p-4">
          <p className="text-ink-secondary text-sm leading-relaxed whitespace-pre-wrap">
            {overall}
          </p>
        </div>
      )}

      {steps.length > 0 && (
        <div>
          <h4 className="text-ink mb-3 flex items-center gap-2 text-sm font-semibold">
            <Brain className="h-4 w-4 text-purple-500" /> 推理过程
          </h4>
          <div className="space-y-2">
            {steps.map((step, i) => (
              <ReasoningStepCard key={step.step} step={step} index={i} />
            ))}
          </div>
        </div>
      )}

      {Object.values(mc).some(Boolean) && (
        <div>
          <h4 className="text-ink mb-3 flex items-center gap-2 text-sm font-semibold">
            <FlaskConical className="h-4 w-4 text-blue-500" /> 方法论推导链
          </h4>
          <div className="space-y-3">
            {mc.problem_definition && <ChainItem label="问题定义" text={mc.problem_definition} />}
            {mc.core_hypothesis && <ChainItem label="核心假设" text={mc.core_hypothesis} />}
            {mc.method_derivation && <ChainItem label="方法推导" text={mc.method_derivation} />}
            {mc.theoretical_basis && <ChainItem label="理论基础" text={mc.theoretical_basis} />}
            {mc.innovation_analysis && (
              <ChainItem label="创新性分析" text={mc.innovation_analysis} />
            )}
          </div>
        </div>
      )}

      {Object.values(ec).some(Boolean) && (
        <div>
          <h4 className="text-ink mb-3 flex items-center gap-2 text-sm font-semibold">
            <Microscope className="h-4 w-4 text-green-500" /> 实验验证链
          </h4>
          <div className="space-y-3">
            {ec.experimental_design && <ChainItem label="实验设计" text={ec.experimental_design} />}
            {ec.baseline_fairness && <ChainItem label="基线公平性" text={ec.baseline_fairness} />}
            {ec.result_validation && <ChainItem label="结果验证" text={ec.result_validation} />}
            {ec.ablation_insights && <ChainItem label="消融洞察" text={ec.ablation_insights} />}
          </div>
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {strengths.length > 0 && (
          <div>
            <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
              <ThumbsUp className="h-4 w-4 text-green-500" /> 优势
            </h4>
            <ul className="space-y-1.5">
              {strengths.map((s, i) => (
                <li
                  key={`strength-${i}`}
                  className="text-ink-secondary flex items-start gap-2 rounded-xl bg-green-500/5 px-3 py-2.5 text-sm dark:bg-green-500/10"
                >
                  <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-green-500" />
                  {s}
                </li>
              ))}
            </ul>
          </div>
        )}
        {weaknesses.length > 0 && (
          <div>
            <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
              <ThumbsDown className="h-4 w-4 text-red-500" /> 不足
            </h4>
            <ul className="space-y-1.5">
              {weaknesses.map((w, i) => (
                <li
                  key={`weakness-${i}`}
                  className="text-ink-secondary flex items-start gap-2 rounded-xl bg-red-500/5 px-3 py-2.5 text-sm dark:bg-red-500/10"
                >
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-red-500" />
                  {w}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {suggestions.length > 0 && (
        <div>
          <h4 className="text-ink mb-2 flex items-center gap-1.5 text-sm font-medium">
            <Lightbulb className="h-4 w-4 text-amber-500" /> 未来研究建议
          </h4>
          <ul className="space-y-1.5">
            {suggestions.map((f, i) => (
              <li
                key={`suggestion-${i}`}
                className="text-ink-secondary flex items-start gap-2 rounded-xl bg-amber-500/5 px-3 py-2.5 text-sm dark:bg-amber-500/10"
              >
                <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                {f}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default ReasoningPanel;
