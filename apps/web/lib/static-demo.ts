import type {
  Actor,
  AdminFailure,
  AdminPipeline,
  AdminSource,
  EvaluationSummary,
  NotificationItem,
  Opportunity,
  OpportunityDetail,
  PipelineScenario,
  PipelineScenarioSummary,
  PipelineStage,
  Preferences,
  Profile,
  ProfileWrite,
  Release,
} from "./api";

const now = "2026-09-18T12:00:00Z";
const userActor: Actor = {
  owner_id: "synthetic-demo-user",
  role: "user",
  csrf_token: "static-demo",
  synthetic_demo: true,
};

let profile: Profile = {
  id: "profile-static",
  owner_user_id: "synthetic-demo-user",
  display_name: "Synthetic AI Systems",
  synthetic_demo: true,
  regions: ["서울", "경기"],
  industries: ["AI", "소프트웨어"],
  capabilities: ["LLM", "OCR", "STT", "시스템 통합"],
  certifications: ["소프트웨어사업자"],
  employee_band: "11-30",
  min_contract_amount: "50000000",
  max_contract_amount: "500000000",
  contract_currency: "KRW",
  excluded_keywords: ["토목", "건축"],
};

let preferences: Preferences = {
  enabled: true,
  channels: ["local"],
  triggers: [
    "new_high_relevance",
    "watched_material_change",
    "deadline_changed",
    "eligibility_changed",
    "outcome_published",
  ],
};

const baseOpportunities: Opportunity[] = [
  {
    id: "opp-ai-contact-center",
    title: "AI 기반 민원상담 시스템 구축",
    buyer_name: "서울 디지털행정원",
    procurement_type: "용역",
    lifecycle_stage: "amendment",
    estimated_amount: "280000000",
    currency: "KRW",
    published_at: "2026-09-10T09:00:00Z",
    closes_at: "2026-10-02T09:00:00Z",
    status: "open",
    current_version_id: "ver-ai-2",
    eligibility: {
      id: "elig-ai",
      eligible: true,
      hard_failures: [],
      warnings: [
        {
          code: "REGION_REVIEW",
          field: "regions",
          message: "서울 소재 조건을 최종 원문에서 다시 확인해야 합니다.",
          evidence: [{ source: "amendment", page: 2 }],
        },
      ],
      ruleset_version: "eligibility-v1",
    },
    ranking: {
      id: "rank-ai",
      recommended: true,
      final_score: "0.91",
      features: { capability_overlap: "0.95", budget_fit: "0.90", recency: "0.88" },
      explanation: { summary: "LLM·OCR 역량과 예산 범위가 기업 프로필에 부합합니다." },
      as_of: now,
      evaluation_epoch: "2026-09-static",
      ranking_version: "rank-v1",
    },
    watched: true,
    changed_at: "2026-09-16T03:00:00Z",
    decision_status: "ready",
  },
  {
    id: "opp-ai-document",
    title: "AI 문서분류·OCR 자동화 플랫폼 고도화",
    buyer_name: "공공데이터지원원",
    procurement_type: "용역",
    lifecycle_stage: "tender",
    estimated_amount: "180000000",
    currency: "KRW",
    published_at: "2026-09-14T01:00:00Z",
    closes_at: "2026-09-29T09:00:00Z",
    status: "open",
    current_version_id: "ver-doc-1",
    eligibility: {
      id: "elig-doc",
      eligible: true,
      hard_failures: [],
      warnings: [],
      ruleset_version: "eligibility-v1",
    },
    ranking: {
      id: "rank-doc",
      recommended: true,
      final_score: "0.86",
      features: { capability_overlap: "0.93", budget_fit: "0.84", recency: "0.92" },
      explanation: { summary: "OCR·문서 처리 역량과 직접적으로 맞닿아 있습니다." },
      as_of: now,
      evaluation_epoch: "2026-09-static",
      ranking_version: "rank-v1",
    },
    watched: false,
    changed_at: "2026-09-14T01:00:00Z",
    decision_status: "ready",
  },
  {
    id: "opp-data-platform",
    title: "공공 데이터 수집·추천 플랫폼 운영",
    buyer_name: "산업정보진흥원",
    procurement_type: "용역",
    lifecycle_stage: "pre-specification",
    estimated_amount: "420000000",
    currency: "KRW",
    published_at: "2026-09-17T02:00:00Z",
    closes_at: "2026-10-10T09:00:00Z",
    status: "preview",
    current_version_id: "ver-data-1",
    eligibility: {
      id: "elig-data",
      eligible: false,
      hard_failures: [
        {
          code: "CERT_REQUIRED",
          field: "certifications",
          message: "필수 보안 인증 확인이 필요합니다.",
          evidence: [{ source: "spec", page: 4 }],
        },
      ],
      warnings: [],
      ruleset_version: "eligibility-v1",
    },
    ranking: {
      id: "rank-data",
      recommended: false,
      final_score: "0.74",
      features: { capability_overlap: "0.82", budget_fit: "0.71", recency: "0.96" },
      explanation: { summary: "기술 관련도는 높지만 필수 인증 게이트를 통과하지 못했습니다." },
      as_of: now,
      evaluation_epoch: "2026-09-static",
      ranking_version: "rank-v1",
    },
    watched: false,
    changed_at: "2026-09-17T02:00:00Z",
    decision_status: "ready",
  },
];

const details: Record<string, OpportunityDetail> = Object.fromEntries(
  baseOpportunities.map((opportunity) => [
    opportunity.id,
    {
      ...opportunity,
      versions:
        opportunity.id === "opp-ai-contact-center"
          ? [
              {
                id: "ver-ai-1",
                version_number: 1,
                source_record_id: "R26BK-AI-001:000",
                effective_at: "2026-09-10T09:00:00Z",
                transition_kind: "initial",
                created_at: "2026-09-10T09:05:00Z",
                normalized_json: {
                  estimated_amount: "320000000",
                  required_capabilities: ["LLM"],
                  region_restriction: null,
                  deadline: "2026-09-30T09:00:00Z",
                },
              },
              {
                id: "ver-ai-2",
                version_number: 2,
                source_record_id: "R26BK-AI-001:001",
                effective_at: "2026-09-16T03:00:00Z",
                transition_kind: "amendment",
                created_at: "2026-09-16T03:05:00Z",
                normalized_json: {
                  estimated_amount: "280000000",
                  required_capabilities: ["LLM", "STT"],
                  region_restriction: "서울 소재 기업",
                  deadline: "2026-10-02T09:00:00Z",
                },
              },
            ]
          : [
              {
                id: opportunity.current_version_id ?? `${opportunity.id}-v1`,
                version_number: 1,
                source_record_id: `${opportunity.id}:000`,
                effective_at: opportunity.published_at ?? now,
                transition_kind: "initial",
                created_at: opportunity.published_at ?? now,
                normalized_json: {
                  estimated_amount: opportunity.estimated_amount,
                  lifecycle_stage: opportunity.lifecycle_stage,
                },
              },
            ],
      timeline: {
        opportunity_ids: [opportunity.id],
        active_links:
          opportunity.id === "opp-ai-contact-center"
            ? [
                {
                  id: "link-ai",
                  parent_opportunity_id: "opp-ai-contact-center",
                  child_opportunity_id: "opp-ai-contact-center",
                  relation_type: "amends",
                  confidence: "1.0000",
                  link_method: "deterministic-source-key",
                  status: "active",
                  evidence_json: { notice_number: "R26BK-AI-001" },
                  created_at: "2026-09-16T03:05:00Z",
                  retracted_at: null,
                },
              ]
            : [],
        historical_links: [],
      },
      deltas: {
        current_inputs_ready: true,
        items:
          opportunity.id === "opp-ai-contact-center"
            ? [
                {
                  id: "delta-ai-1",
                  from_version_id: "ver-ai-1",
                  to_version_id: "ver-ai-2",
                  field_changes_json: {
                    estimated_amount: { before: "320000000", after: "280000000" },
                    required_capabilities: { added: ["STT"] },
                    region_restriction: { before: null, after: "서울 소재 기업" },
                    deadline: { before: "2026-09-30", after: "2026-10-02" },
                  },
                  document_changes_json: { replaced: ["제안요청서_v2.pdf"] },
                  impact_level: "HIGH",
                  impact_reasons_json: ["예산 감소", "필수 기술 추가", "참가 조건 추가"],
                  comparison_kind: "successive-version",
                  created_at: "2026-09-16T03:06:00Z",
                  applicable_now: true,
                },
              ]
            : [],
      },
      documents: [
        {
          id: "doc-spec",
          filename: "합성_제안요청서.pdf",
          media_type: "application/pdf",
          sha256: "synthetic-demo-document",
          byte_size: 245760,
          download_status: "downloaded",
          original_url: null,
          parses: [
            {
              id: "parse-spec",
              parser_kind: "native-pdf",
              parser_version: "1",
              status: "parsed",
              page_count: 12,
              quality_json: { synthetic: true, text_coverage: 0.98 },
            },
          ],
        },
      ],
      extraction: {
        status: "validated",
        id: `extract-${opportunity.id}`,
        extractor_version: "deterministic-static-demo-v1",
        schema_version: "procure-delta-extraction-v1",
        input_fingerprint: "static-demo",
        trusted_fields: {
          required_capabilities: opportunity.id === "opp-ai-contact-center" ? ["LLM", "STT"] : ["OCR", "문서분류"],
          estimated_amount: opportunity.estimated_amount,
        },
        evidence: {
          required_capabilities: [{ page: 3, quote: "합성 문서 근거: 필수 수행 역량" }],
        },
        conflicts: {},
        validation_errors: [],
      },
    },
  ]),
) as Record<string, OpportunityDetail>;

const watchedIds = new Set<string>(["opp-ai-contact-center"]);
const notifications: NotificationItem[] = [
  {
    id: "notice-1",
    opportunity_id: "opp-ai-contact-center",
    delta_id: "delta-ai-1",
    channel: "local",
    template_key: "watched_material_change",
    status: "delivered",
    attempt_count: 1,
    next_attempt_at: null,
    sent_at: "2026-09-16T03:07:00Z",
    payload: { title: "참가 조건과 예산이 변경되었습니다." },
    receipt_id: "receipt-static-1",
    received_at: "2026-09-16T03:07:01Z",
  },
  {
    id: "notice-2",
    opportunity_id: "opp-ai-contact-center",
    delta_id: "delta-ai-1",
    channel: "local",
    template_key: "deadline_changed",
    status: "delivered",
    attempt_count: 1,
    next_attempt_at: null,
    sent_at: "2026-09-16T03:07:00Z",
    payload: { title: "마감일이 10월 2일로 변경되었습니다." },
    receipt_id: "receipt-static-2",
    received_at: "2026-09-16T03:07:01Z",
  },
];

const evaluation: EvaluationSummary = {
  status: "measured",
  synthetic: true,
  public_real_records: 0,
  measured_at: "2026-09-18T13:39:50Z",
  dataset_version: "synthetic-regression-v1",
  dataset_sha256: "see-repository-artifact",
  source_sha256: "see-repository-artifact",
  extraction_accuracy: 1,
  extraction_correct: 30,
  extraction_support: 30,
  delta_precision: 1,
  delta_recall: 1,
  delta_support: 7,
  lifecycle_precision: 1,
  lifecycle_resolved: 2,
  lifecycle_cases: 5,
  replay_queries: 3,
  ocr_accuracy: 17 / 18,
  ocr_correct: 17,
  ocr_support: 18,
  ocr_language: "English synthetic images",
  hosted_evaluated: false,
  notice: "작은 합성 회귀셋의 저장된 측정값입니다. 실제 조달 성능을 의미하지 않습니다.",
};

function opportunityView(item: Opportunity): Opportunity {
  return { ...item, watched: watchedIds.has(item.id) };
}

const pipelineCatalog: PipelineScenarioSummary[] = [
  {
    id: "new-opportunity",
    title: "신규 공고",
    description: "수집부터 추천·알림 판단까지",
  },
  {
    id: "amendment-eligibility-change",
    title: "정정으로 조건 변경",
    description: "버전 변경이 Delta와 참여 가능 여부에 미치는 영향",
  },
  {
    id: "failure-recovery",
    title: "장애와 복구",
    description: "재시도·비재시도·종료 실패 경계를 확인",
  },
];

const pipelineOrder: Array<
  [string, string, PipelineStage["kind"]]
> = [
  ["collect", "수집", "system"],
  ["dedupe", "중복 제거", "system"],
  ["normalize", "정규화", "deterministic"],
  ["documents", "문서 파싱", "system"],
  ["ocr-route", "OCR 라우팅", "ocr"],
  ["extract", "구조화 추출", "deterministic"],
  ["validate", "스키마·근거 검증", "deterministic"],
  ["lifecycle", "생애주기 연결", "deterministic"],
  ["delta", "Delta", "deterministic"],
  ["eligibility", "참여 조건", "deterministic"],
  ["ranking", "관련도 순위", "deterministic"],
  ["notification", "알림 판단", "notification"],
];

function pipelineStage(
  id: string,
  label: string,
  kind: PipelineStage["kind"],
  status: PipelineStage["status"] = "passed",
  patch: Partial<PipelineStage> = {},
): PipelineStage {
  return {
    id,
    label,
    kind,
    status,
    input: {},
    output: {},
    evidence: [],
    decision: {},
    measured_duration_ms: null,
    notice: null,
    ...patch,
  };
}

function newOpportunityScenario(): PipelineScenario {
  const stages = pipelineOrder.map(([id, label, kind]) =>
    pipelineStage(id, label, kind),
  );
  const byId = new Map(stages.map((stage) => [stage.id, stage]));
  Object.assign(byId.get("collect")!, {
    output: { source_record_id: "control-room-tender" },
    notice: "합성 시나리오 · 외부 네트워크 호출 없음",
  });
  Object.assign(byId.get("ocr-route")!, {
    status: "not_run",
    decision: { route_to_ocr: false },
    notice: "HTML native parsing 품질이 충분해 OCR을 실행하지 않았습니다.",
  });
  Object.assign(byId.get("extract")!, {
    output: { extractor: "deterministic-labels-v1", hosted_llm: false },
    notice: "로컬 deterministic extractor · hosted LLM 호출 없음",
  });
  Object.assign(byId.get("delta")!, {
    status: "not_run",
    notice: "최초 관측 버전에는 비교 대상이 없습니다.",
  });
  Object.assign(byId.get("eligibility")!, {
    output: {
      eligible: true,
      allows_recommendation: true,
      hard_failure_codes: [],
      warning_codes: [],
    },
    decision: { hard_gate: "allowed" },
  });
  Object.assign(byId.get("ranking")!, {
    output: { score: 0.88, recommended: true },
    decision: { eligibility_overrides_rank: true },
  });
  Object.assign(byId.get("notification")!, {
    output: { trigger: "new_high_relevance" },
    decision: { external_delivery: false },
    notice: "알림 트리거 판단만 재생하며 외부 메시지를 보내지 않습니다.",
  });
  return {
    scenario_id: "new-opportunity",
    title: "신규 공고",
    description: "수집부터 추천·알림 판단까지",
    synthetic: true,
    source_scope: "packaged_fixture",
    stages,
  };
}

function amendmentScenario(): PipelineScenario {
  const stages = pipelineOrder.map(([id, label, kind]) =>
    pipelineStage(id, label, kind),
  );
  const byId = new Map(stages.map((stage) => [stage.id, stage]));
  Object.assign(byId.get("collect")!, {
    output: { observed_revision: "control-room-tender", amendment: true },
    notice: "합성 정정 시나리오 · 외부 네트워크 호출 없음",
  });
  Object.assign(byId.get("ocr-route")!, {
    status: "not_run",
    decision: { route_to_ocr: false },
    notice: "HTML native parsing 경로이므로 OCR은 실행하지 않았습니다.",
  });
  Object.assign(byId.get("extract")!, {
    output: { extractor: "deterministic-labels-v1", hosted_llm: false },
    notice: "hosted LLM이 아닌 재현 가능한 로컬 추출 경로입니다.",
  });
  Object.assign(byId.get("delta")!, {
    output: {
      changed_fields: {
        budget: {
          before: { estimated_amount: "320000000", currency: "KRW" },
          after: { estimated_amount: "280000000", currency: "KRW" },
        },
        regions: { before: ["Seoul"], after: ["Busan"] },
      },
    },
    decision: {
      impact: "high",
      reason_codes: ["budget_decreased", "region_restriction_changed"],
    },
  });
  Object.assign(byId.get("eligibility")!, {
    output: {
      before: {
        eligible: true,
        allows_recommendation: true,
        hard_failure_codes: [],
        warning_codes: [],
      },
      after: {
        eligible: false,
        allows_recommendation: false,
        hard_failure_codes: ["region_not_served"],
        warning_codes: [],
      },
    },
    decision: {
      changed: true,
      rule: "hard eligibility precedes relevance",
    },
  });
  Object.assign(byId.get("ranking")!, {
    output: {
      before: { score: 0.9, recommended: true },
      after: { score: 0.89, recommended: false },
    },
    decision: {
      eligibility_overrides_rank: true,
      after_score_still_visible: 0.89,
    },
  });
  Object.assign(byId.get("notification")!, {
    input: { watched: true, material_change: true },
    output: { trigger: "watched_material_change" },
    decision: { should_enqueue: true, external_delivery: false },
    notice:
      "관심 공고의 material change 알림 판단을 재생합니다. 외부 메시지는 보내지 않습니다.",
  });
  return {
    scenario_id: "amendment-eligibility-change",
    title: "정정으로 조건 변경",
    description: "버전 변경이 Delta와 참여 가능 여부에 미치는 영향",
    synthetic: true,
    source_scope: "packaged_fixture",
    stages,
  };
}

function failureScenario(): PipelineScenario {
  const stages = pipelineOrder.map(([id, label, kind]) =>
    pipelineStage(id, label, kind, id === "collect" ? "warning" : "blocked", {
      notice:
        id === "collect"
          ? "합성 HTTP transport 주입 결과"
          : "수집 실패 경계를 설명하는 시나리오이므로 후속 처리를 실행하지 않습니다.",
    }),
  );
  stages[0].input = { scope: "http_transport_injection" };
  stages[0].output = {
    transport_cases: [
      { name: "timeout-recovery", attempts: 3, succeeded: true },
      { name: "rate-limit-recovery", attempts: 2, succeeded: true },
      { name: "server-error-terminal", attempts: 3, succeeded: false },
      { name: "forbidden-not-retried", attempts: 1, succeeded: false },
    ],
  };
  stages[0].decision = {
    retryable: ["timeout", "429", "5xx"],
    non_retryable: ["403"],
    terminal_after_bounded_attempts: true,
  };
  return {
    scenario_id: "failure-recovery",
    title: "장애와 복구",
    description: "재시도·비재시도·종료 실패 경계를 확인",
    synthetic: true,
    source_scope: "committed_verification_artifact",
    stages,
  };
}

export function staticPipelineScenarios(): PipelineScenarioSummary[] {
  return pipelineCatalog.map((row) => ({ ...row }));
}

export function staticPipelineScenario(id: string): PipelineScenario {
  if (id === "new-opportunity") return newOpportunityScenario();
  if (id === "amendment-eligibility-change") return amendmentScenario();
  if (id === "failure-recovery") return failureScenario();
  throw new Error("정적 데모 파이프라인 시나리오를 찾을 수 없습니다.");
}

function method(init: RequestInit) {
  return (init.method ?? "GET").toUpperCase();
}

async function staticDemoValue(path: string, init: RequestInit = {}): Promise<unknown> {
  const url = new URL(path, "https://static-demo.invalid");
  const pathname = url.pathname;
  const requestMethod = method(init);

  if (pathname === "/auth/session" || pathname === "/auth/demo-login") return userActor;
  if (pathname === "/auth/logout") return undefined;

  if (pathname === "/company-profile") {
    if (requestMethod === "PATCH" && init.body) {
      const patch = JSON.parse(String(init.body)) as Partial<ProfileWrite>;
      profile = { ...profile, ...patch };
    }
    return profile;
  }

  if (pathname === "/opportunities") {
    const q = (url.searchParams.get("q") ?? "").toLowerCase();
    const stage = url.searchParams.get("lifecycle_stage") ?? "";
    const eligibleOnly = url.searchParams.get("eligible_only") === "true";
    const items = baseOpportunities
      .filter((item) => !q || `${item.title} ${item.buyer_name}`.toLowerCase().includes(q))
      .filter((item) => !stage || item.lifecycle_stage === stage)
      .filter((item) => !eligibleOnly || Boolean(item.eligibility?.eligible && !item.eligibility.warnings.length))
      .map(opportunityView);
    return { items, next_cursor: null };
  }

  const watchMatch = pathname.match(/^\/opportunities\/([^/]+)\/watch$/);
  if (watchMatch) {
    const id = watchMatch[1];
    if (requestMethod === "DELETE") watchedIds.delete(id);
    else watchedIds.add(id);
    return { watched: watchedIds.has(id) };
  }

  const detailMatch = pathname.match(/^\/opportunities\/([^/]+)$/);
  if (detailMatch) {
    const item = details[detailMatch[1]];
    if (!item) throw new Error("정적 데모 공고를 찾을 수 없습니다.");
    return { ...item, watched: watchedIds.has(item.id) };
  }

  if (pathname === "/watchlist") {
    return { items: baseOpportunities.filter((item) => watchedIds.has(item.id)).map(opportunityView), next_cursor: null };
  }

  if (pathname === "/notifications") return { items: notifications, next_cursor: null };

  if (pathname === "/notifications/preferences") {
    if (requestMethod === "PUT" && init.body) preferences = JSON.parse(String(init.body)) as Preferences;
    return preferences;
  }

  if (pathname === "/evaluation/summary") return evaluation;

  if (pathname === "/demo/pipeline/scenarios") return staticPipelineScenarios();

  const pipelineScenarioMatch = pathname.match(
    /^\/demo\/pipeline\/scenarios\/([^/]+)$/,
  );
  if (pipelineScenarioMatch)
    return staticPipelineScenario(decodeURIComponent(pipelineScenarioMatch[1]));

  if (pathname === "/admin/pipeline") {
    const pipeline: AdminPipeline = {
      observed_at: now,
      records_fetched_today: 1248,
      new_records_today: 183,
      changed_versions_today: 26,
      duplicates_skipped_today: 1039,
      parsing_failures: 2,
      ocr_fallbacks: 17,
      structured_extraction_count: 162,
      schema_validation_failures: 3,
      retry_queue_count: 1,
      dlq_count: 0,
      worker_queue_depth: 0,
      scheduler_queue_depth: 0,
      worker_heartbeat: true,
      scheduler_heartbeat: true,
      worker_activity: { completed: 246, failed: 2, retried: 2, ongoing: 0 },
      scheduler_activity: { completed: 24, failed: 0, retried: 0, ongoing: 0 },
      parsing: [{ kind: "pdf", status: "parsed", count: 145 }],
      extraction: [{ kind: "deterministic", status: "validated", count: 162 }],
    };
    return pipeline;
  }

  if (pathname === "/admin/sources") {
    const sources: AdminSource[] = [
      {
        id: "source-static",
        code: "synthetic-public-demo",
        display_name: "Synthetic public demo source",
        enabled: true,
        polling_interval_seconds: 300,
        last_success_at: now,
        last_failure_at: null,
      },
    ];
    return sources;
  }

  if (pathname === "/admin/failures") {
    const failures: AdminFailure[] = [];
    return { items: failures, next_cursor: null };
  }

  if (pathname === "/release") {
    const release: Release = {
      name: "ProcureDelta static public demo",
      version: "0.1.0",
      revision: "github-main",
      authentication: "synthetic-static-demo",
      extraction_mode: "stored-synthetic-evidence",
    };
    return release;
  }

  throw new Error(`정적 데모에서 지원하지 않는 경로입니다: ${pathname}`);
}

export async function staticDemoRequest<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  return (await staticDemoValue(path, init)) as T;
}

export function staticDocumentUrl(id: string) {
  void id;
  return "#synthetic-document";
}