import { useState, useEffect } from "react";
import { ChevronDown, CheckCircle2, Loader2, Circle, Bot } from "lucide-react";

interface CompactProgressCardProps {
  isLoading?: boolean;
  isResponseComplete?: boolean;
}

const stageSubsteps: Record<string, string[]> = {
  "Parsing intent": [
    "Extracting entities, context, and query structure"
  ],
  "Identifying the companies": [
    "Validating company names",
    "Matching ticker symbols"
  ],
  "Searching knowledge": [
    "Scanning relevant documents",
    "Aggregating results",
    "Cross-referencing data"
  ],
  "Collecting the latest news": [
    "Searching news feeds",
    "Filtering relevance",
    "Organizing by date"
  ],
  "Reasoning & synthesis": [
    "Cross-referencing facts",
    "Resolving contradictions",
    "Weighting evidence"
  ],
  "Composing response": [
    "Structuring content",
    "Formatting for readability",
    "Adding citations"
  ],
  "Finalizing": [
    "Quality check",
    "Optimization"
  ]
};

const stages = Object.keys(stageSubsteps);

export function CompactProgressCard({
  isLoading = false,
  isResponseComplete = false
}: CompactProgressCardProps) {
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [activeSubstepIndex, setActiveSubstepIndex] = useState(0);
  const [isExpanded, setIsExpanded] = useState(true);

  // Auto-advance steps when loading - 5 seconds per step
  useEffect(() => {
    if (!isLoading || isResponseComplete) return;

    const interval = setInterval(() => {
      setCurrentStepIndex((prev) => {
        if (prev < stages.length - 1) {
          setActiveSubstepIndex(0); // Reset substep when moving to next step
          return prev + 1;
        }
        return prev;
      });
    }, 3000); // 5 seconds per step

    return () => clearInterval(interval);
  }, [isLoading, isResponseComplete]);

  // Auto-advance substeps
  useEffect(() => {
    if (!isLoading || isResponseComplete) return;

    const currentStage = stages[currentStepIndex];
    const substeps = stageSubsteps[currentStage] || [];

    const substepInterval = setInterval(() => {
      setActiveSubstepIndex((prev) => {
        if (prev < substeps.length - 1) {
          return prev + 1;
        }
        return prev;
      });
    }, 1500); // 1.5 seconds per substep

    return () => clearInterval(substepInterval);
  }, [isLoading, isResponseComplete, currentStepIndex]);

  // Auto-collapse when response is complete
  useEffect(() => {
    if (isResponseComplete) {
      setCurrentStepIndex(stages.length - 1);
      setActiveSubstepIndex(0);
      setIsExpanded(false);
    }
  }, [isResponseComplete]);

  const completedStepsCount = isResponseComplete
    ? stages.length
    : currentStepIndex;

  return (
    <div className="flex gap-3">
      {/* Agent Icon */}
      <div className="size-8 rounded-lg flex items-center justify-center flex-shrink-0 shadow-sm bg-indigo-600">
        <Bot className="size-4 text-white" />
      </div>

      {/* Progress Card */}
      <div className="flex-1 bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm">
        {/* Header */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors"
        >
          <div className="flex items-center gap-2 flex-1">
            {isLoading && !isResponseComplete ? (
              <Loader2 className="size-4 text-indigo-600 animate-spin flex-shrink-0" />
            ) : (
              <CheckCircle2 className="size-4 text-indigo-600 flex-shrink-0" />
            )}
            <div className="text-left">
              <div className="text-xs font-semibold text-gray-900">
                {isLoading && !isResponseComplete ? "Analysing" : "COMPLETED"}
              </div>
              <div className="text-xs text-gray-600 mt-0.5">
              </div>
            </div>
          </div>
          <ChevronDown
            className={`size-4 text-gray-600 flex-shrink-0 transition-transform ${
              isExpanded ? "rotate-180" : ""
            }`}
          />
        </button>

        {/* Content with Vertical Progress Line */}
        {isExpanded && (
          <div className="px-4 pb-3 pt-2 border-t border-gray-100 max-h-48 overflow-y-auto">
            <div className="relative pl-4">
              {/* Background vertical line */}
              <div className="absolute left-1.5 top-0 bottom-0 w-0.5 bg-gray-200" />

              {/* Progress line (animated) */}
              <div
                className="absolute left-1.5 top-0 w-0.5 bg-indigo-600 transition-all duration-500"
                style={{
                  height: `${((completedStepsCount + (activeSubstepIndex / (stageSubsteps[stages[currentStepIndex]]?.length || 1))) / stages.length) * 100}%`
                }}
              />

              {/* Stages - Only show completed and current active */}
              <div className="space-y-3">
                {stages.map((stage, idx) => {
                  const isCompleted = idx < currentStepIndex;
                  const isActive = idx === currentStepIndex && isLoading && !isResponseComplete;
                  const isUpcoming = idx > currentStepIndex;
                  const substeps = stageSubsteps[stage] || [];

                  // Only render completed or active stages, hide upcoming
                  if (isUpcoming) return null;

                  return (
                    <div key={idx} className="relative">
                      {/* Stage connector */}
                      <div className="flex gap-2">
                        <div className="flex flex-col items-center -ml-5">
                          <div
                            className={`size-4 rounded-full flex items-center justify-center border-3 transition-all flex-shrink-0 ${
                              isCompleted
                                ? "bg-indigo-600 border-indigo-100"
                                : isActive
                                ? "bg-white border-indigo-600"
                                : "bg-white border-gray-300"
                            }`}
                          >
                            {isCompleted ? (
                              <CheckCircle2 className="size-2.5 text-white" />
                            ) : isActive ? (
                              <Loader2 className="size-2.5 text-indigo-600 animate-spin" />
                            ) : (
                              <Circle className="size-1.5 text-gray-300" />
                            )}
                          </div>
                        </div>

                        {/* Stage content */}
                        <div className="flex-1 pb-1">
                          <h3
                            className={`text-xs font-semibold transition-colors ${
                              isCompleted || isActive
                                ? "text-gray-900"
                                : "text-gray-500"
                            }`}
                          > 
                            {stage}
                          </h3>

                          {/* Substeps - only show for active stage, not completed */}
                          {isActive && substeps.length > 0 && (
                            <div className="mt-1.5 space-y-1">
                              {substeps.map((substep, subIdx) => {
                                const isSubstepCompleted = subIdx < activeSubstepIndex;
                                const isActiveSubstep = subIdx === activeSubstepIndex;

                                return (
                                  <div
                                    key={subIdx}
                                    className="flex items-center gap-1.5"
                                  >
                                    <div
                                      className={`size-1 rounded-full transition-colors flex-shrink-0 ${
                                        isSubstepCompleted || isActiveSubstep
                                          ? "bg-indigo-500"
                                          : "bg-gray-300"
                                      }`}
                                    />
                                    <span
                                      className={`text-xs transition-colors line-clamp-2 ${
                                        isSubstepCompleted || isActiveSubstep
                                          ? "text-gray-700"
                                          : "text-gray-500"
                                      }`}
                                    >
                                      {substep}
                                      {isActiveSubstep && (
                                        <span className="ml-1 inline-block">
                                          <Loader2 className="size-1.5 animate-spin inline text-indigo-600" />
                                        </span>
                                      )}
                                    </span>
                                  </div>
                                );
                              })}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
