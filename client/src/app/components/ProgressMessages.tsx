import { useState, useEffect } from "react";
import { ChevronDown, CheckCircle2, Loader2, Circle } from "lucide-react";

export interface ProgressMessage {
  stage: string;
  timestamp: string;
}

interface ProgressMessagesProps {
  messages: ProgressMessage[];
  isLoading?: boolean;
}

// Substeps for each stage
const stageSubsteps: Record<string, string[]> = {
  "parsing intent": [
    "Extracting entities"
  ],
  "Identifying the companies": [
    "Validating company names",
  ],
  "Searching Knowledge": [
    "Scanning relevant documents and sources",
    "Aggregating results",
    "Cross-referencing data"
  ],
  "Collecting the latest news": [
    "Searching news feeds",
    "Filtering relevance",
  ],
  "Composing response": [
    "Cross-referencing facts",
    "Resolving contradictions",
    "Finalizing response structure"
  ]
};

const stageDurations: Record<string, number> = {
  "Extracting user intent": 634,
  "Identifying the companies": 856,
  "Fetching relevant data": 1245,
  "Collecting the latest news": 1523,
  "Generating the response": 2045
};

export function ProgressMessages({ messages, isLoading = false }: ProgressMessagesProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [activeSubstepIndex, setActiveSubstepIndex] = useState(0);

  // Auto-advance steps every 30 seconds for demo
  useEffect(() => {
    if (!isLoading) return;

    const interval = setInterval(() => {
      setCurrentStepIndex((prev) => {
        if (prev < 4) {
          setActiveSubstepIndex(0); // Reset substep when moving to next step
          return prev + 1;
        }
        return prev;
      });
    }, 10000); // 10 seconds

    return () => clearInterval(interval);
  }, [isLoading]);

  // Auto-advance substeps every 10 seconds
  useEffect(() => {
    if (!isLoading) return;

    const stages = [
      "Extracting user intent",
      "Identifying the companies",
      "Fetching relevant data",
      "Collecting the latest news",
      "Generating the response"
    ];

    const currentStage = stages[currentStepIndex];
    const substeps = stageSubsteps[currentStage] || [];

    const substepInterval = setInterval(() => {
      setActiveSubstepIndex((prev) => {
        if (prev < substeps.length - 1) {
          return prev + 1;
        }
        return prev;
      });
    }, 30000); // 30 seconds per substep

    return () => clearInterval(substepInterval);
  }, [isLoading, currentStepIndex]);

  const stages = [
    "Extracting user intent",
    "Identifying the companies",
    "Fetching relevant data",
    "Collecting the latest news",
    "Generating the response"
  ];

  const completedStepsCount = isLoading ? currentStepIndex : stages.length;
  const totalSteps = stages.length;

  const formatDuration = (ms: number) => {
    if (ms < 1000) return `${ms}ms`;
    return `${(ms / 1000).toFixed(1)}s`;
  };

  return (
    <div className="bg-white border border-gray-200 rounded-lg overflow-hidden shadow-sm">
      {/* Header */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-4 px-6 py-4 hover:bg-gray-50 transition-colors"
      >
        <div className="flex items-center gap-3 flex-1">
          <div className="size-10 rounded-lg bg-indigo-100 flex items-center justify-center flex-shrink-0">
            {isLoading ? (
              <Loader2 className="size-5 text-indigo-600 animate-spin" />
            ) : (
              <CheckCircle2 className="size-5 text-emerald-600" />
            )}
          </div>
          <div className="text-left">
            <div className="text-sm font-semibold text-gray-900">
              {isLoading ? "PROCESSING" : "PROCESS COMPLETE"}
            </div>
            <div className="text-xs text-gray-500 mt-0.5">
              {completedStepsCount}/{totalSteps} steps{" "}
              {isLoading && `• ${formatDuration(stageDurations[stages[currentStepIndex]] || 0)}`}
            </div>
          </div>
        </div>
        <ChevronDown
          className={`size-5 text-gray-400 flex-shrink-0 transition-transform ${
            isExpanded ? "rotate-180" : ""
          }`}
        />
      </button>

      {/* Progress Line Background */}
      {isExpanded && (
        <div className="px-6 pb-6 pt-4">
          {/* Vertical Progress Line */}
          <div className="relative pl-12">
            {/* Background line */}
            <div className="absolute left-4 top-0 bottom-0 w-1 bg-gray-100" />
            
            {/* Progress line (animated) */}
            <div
              className="absolute left-4 top-0 w-1 bg-gradient-to-b from-blue-500 via-cyan-500 to-cyan-400 transition-all duration-500"
              style={{
                height: `${((completedStepsCount + (activeSubstepIndex / (stageSubsteps[stages[currentStepIndex]]?.length || 1))) / totalSteps) * 100}%`
              }}
            />

            {/* Steps */}
            <div className="space-y-6">
              {stages.map((stage, idx) => {
                const isCompleted = idx < currentStepIndex;
                const isActive = idx === currentStepIndex && isLoading;
                const isUpcoming = idx > currentStepIndex;
                const substeps = stageSubsteps[stage] || [];
                const duration = stageDurations[stage] || 0;

                return (
                  <div key={idx} className="relative">
                    {/* Step circle and connector */}
                    <div className="flex gap-4">
                      <div className="flex flex-col items-center -ml-12">
                        <div
                          className={`size-8 rounded-full flex items-center justify-center border-4 transition-all ${
                            isCompleted
                              ? "bg-emerald-500 border-emerald-100"
                              : isActive
                              ? "bg-white border-indigo-500"
                              : "bg-white border-gray-200"
                          }`}
                        >
                          {isCompleted ? (
                            <CheckCircle2 className="size-5 text-white" />
                          ) : isActive ? (
                            <Loader2 className="size-4 text-indigo-600 animate-spin" />
                          ) : (
                            <Circle className="size-4 text-gray-300" />
                          )}
                        </div>
                      </div>

                      {/* Step content */}
                      <div className="flex-1 pb-4">
                        <div className={`${isUpcoming ? "opacity-40" : ""}`}>
                          {/* Step title and duration */}
                          <div className="flex items-baseline justify-between gap-2 mb-1">
                            <h3 className={`text-sm font-semibold ${
                              isCompleted || isActive
                                ? "text-gray-900"
                                : "text-gray-500"
                            }`}>
                              {stage}
                            </h3>
                            <span className={`text-xs font-medium ${
                              isCompleted ? "text-emerald-600" : "text-gray-400"
                            }`}>
                              {isCompleted && formatDuration(duration)}
                            </span>
                          </div>

                          {/* Substeps - only show for active or completed steps */}
                          {(isActive || isCompleted) && substeps.length > 0 && (
                            <div className="mt-3 space-y-2">
                              {substeps.map((substep, subIdx) => {
                                const isSubstepCompleted = isCompleted || (isActive && subIdx < activeSubstepIndex);
                                const isActiveSubstep = isActive && subIdx === activeSubstepIndex;

                                return (
                                  <div key={subIdx} className="flex items-center gap-2">
                                    <div className={`size-1.5 rounded-full ${
                                      isSubstepCompleted || isActiveSubstep
                                        ? "bg-cyan-500"
                                        : "bg-gray-300"
                                    }`} />
                                    <span className={`text-xs ${
                                      isSubstepCompleted || isActiveSubstep
                                        ? "text-gray-700"
                                        : "text-gray-400"
                                    }`}>
                                      {substep}
                                      {isActiveSubstep && (
                                        <span className="ml-2 inline-block">
                                          <Loader2 className="size-2 animate-spin inline text-cyan-500" />
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
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
