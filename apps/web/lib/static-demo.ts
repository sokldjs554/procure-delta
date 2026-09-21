import type {
  Actor,
  AdminFailure,
  AdminPipeline,
  AdminSource,
  EngineeringEvidence,
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

type StaticEligibilityFacts = {
  regions: string[];
  required_certifications: string[];
};

const staticEligibilityFacts: Record<string, StaticEligibilityFacts> = {
  "opp-ai-contact-center": { regions: ["서울"], required_certifications: [] },
  "opp-ai-document": { regions: ["서울", "경기"], required_certifications: [] },
  "opp-data-platform": { regions: ["서울"], required_certifications: ["ISMS-P"] },
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
      ruleset_version: "hard-eligibility-v1",
    },
    ranking: {
      id: "rank-ai",
      recommended: true,
      final_score: "0.91",
      features: { capability_overlap: "0.95", budget_fit: "0.90", recency: "0.88" },
      explanation: { summary: "LLM·OCR 역량과 예산 범위가 기업 프로필에 부합합니다." },
      as_of: now,
      evaluation_epoch: "2026-09-static",
      ranking_version: "deterministic-baseline-v1",
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
      ruleset_version: "hard-eligibility-v1",
    },
    ranking: {
      id: "rank-doc",
      recommended: true,
      final_score: "0.86",
      features: { capability_overlap: "0.93", budget_fit: "0.84", recency: "0.92" },
      explanation: { summary: "OCR·문서 처리 역량과 직접적으로 맞닿아 있습니다." },
      as_of: now,
      evaluation_epoch: "2026-09-static",
      ranking_version: "deterministic-baseline-v1",
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
      ruleset_version: "hard-eligibility-v1",
    },
    ranking: {
      id: "rank-data",
      recommended: false,
      final_score: "0.74",
      features: { capability_overlap: "0.82", budget_fit: "0.71", recency: "0.96" },
      explanation: { summary: "기술 관련도는 높지만 필수 인증 게이트를 통과하지 못했습니다." },
      as_of: now,
      evaluation_epoch: "2026-09-static",
      ranking_version: "deterministic-baseline-v1",
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
        active_links: [],
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
                  impact_level: "high",
                  impact_reasons_json: ["예산 감소", "필수 기술 추가", "참가 조건 추가"],
                  comparison_kind: "current_transition",
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
          sha256: null,
          byte_size: 245760,
          download_status: "parsed",
          original_url: null,
          parses: [
            {
              id: "parse-spec",
              parser_kind: "native_pdf",
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
        extractor_version: "deterministic-labels-v1",
        schema_version: "1",
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
    status: "sent",
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
    status: "sent",
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
  routes: {
    deterministic: {
      status: "measured",
      support: 30,
      field_accuracy: 1,
      schema_failures: 4,
      grounded_acceptance_rate: 0.5,
      p50_latency_ms: 0.08165599996345918,
      p95_latency_ms: 0.5829165499676494,
      hosted_calls: 0,
      prompt_tokens: null,
      completion_tokens: null,
      reported_cost: null,
      language: null,
      notice: "로컬 deterministic extractor · 합성 회귀셋",
    },
    hosted_all: {
      status: "not_run",
      support: 0,
      field_accuracy: null,
      schema_failures: null,
      grounded_acceptance_rate: null,
      p50_latency_ms: null,
      p95_latency_ms: null,
      hosted_calls: null,
      prompt_tokens: null,
      completion_tokens: null,
      reported_cost: null,
      language: null,
      notice: "explicit hosted opt-in not supplied",
    },
    hosted_gated: {
      status: "not_run",
      support: 0,
      field_accuracy: null,
      schema_failures: null,
      grounded_acceptance_rate: null,
      p50_latency_ms: null,
      p95_latency_ms: null,
      hosted_calls: null,
      prompt_tokens: null,
      completion_tokens: null,
      reported_cost: null,
      language: null,
      notice: "explicit hosted opt-in not supplied",
    },
    ocr: {
      status: "measured",
      support: 18,
      field_accuracy: 17 / 18,
      schema_failures: null,
      grounded_acceptance_rate: null,
      p50_latency_ms: null,
      p95_latency_ms: null,
      hosted_calls: 1,
      prompt_tokens: null,
      completion_tokens: null,
      reported_cost: null,
      language: "eng",
      notice: "English rendered images only; not Korean scans, layouts or production OCR.",
    },
  },
  notice: "작은 합성 회귀셋의 저장된 측정값입니다. 실제 조달 성능을 의미하지 않습니다.",
};

function normalized(value: string) {
  return value.trim().toLocaleLowerCase("ko-KR");
}

function opportunityView(item: Opportunity): Opportunity {
  const facts = staticEligibilityFacts[item.id];
  const hardFailures: NonNullable<Opportunity["eligibility"]>["hard_failures"] = [];
  const warnings: NonNullable<Opportunity["eligibility"]>["warnings"] = [];

  if (facts) {
    if (!profile.regions.length) {
      warnings.push({
        code: "profile_regions_unknown",
        field: "regions",
        message: "기업 활동 지역이 설정되지 않았습니다.",
        evidence: [],
      });
    } else if (
      !facts.regions.some((region) =>
        profile.regions.some((owned) => normalized(owned) === normalized(region)),
      )
    ) {
      hardFailures.push({
        code: "region_not_served",
        field: "regions",
        message: "공고 지역이 기업 활동 지역과 일치하지 않습니다.",
        evidence: [{ source: "static-scenario", regions: facts.regions }],
      });
    }

    const ownedCertifications = new Set(profile.certifications.map(normalized));
    const missingCertifications = facts.required_certifications.filter(
      (certification) => !ownedCertifications.has(normalized(certification)),
    );
    if (missingCertifications.length) {
      hardFailures.push({
        code: "missing_certification",
        field: "required_certifications",
        message: `필수 인증이 없습니다: ${missingCertifications.join(", ")}`,
        evidence: [{ source: "static-scenario", required: missingCertifications }],
      });
    }

    const amount = item.estimated_amount === null ? null : Number(item.estimated_amount);
    const minimum =
      profile.min_contract_amount === null ? null : Number(profile.min_contract_amount);
    const maximum =
      profile.max_contract_amount === null ? null : Number(profile.max_contract_amount);
    if ((minimum !== null || maximum !== null) && profile.contract_currency !== item.currency) {
      warnings.push({
        code: "amount_currency_mismatch",
        field: "currency",
        message: "기업 계약 통화와 공고 통화가 달라 금액 조건을 확정하지 않습니다.",
        evidence: [],
      });
    } else if (amount !== null && Number.isFinite(amount)) {
      if (minimum !== null && Number.isFinite(minimum) && amount < minimum) {
        hardFailures.push({
          code: "amount_below_minimum",
          field: "estimated_amount",
          message: "공고 금액이 기업 최소 계약 금액보다 작습니다.",
          evidence: [],
        });
      }
      if (maximum !== null && Number.isFinite(maximum) && amount > maximum) {
        hardFailures.push({
          code: "amount_above_maximum",
          field: "estimated_amount",
          message: "공고 금액이 기업 최대 계약 금액보다 큽니다.",
          evidence: [],
        });
      }
    }
  }

  const eligible = hardFailures.length === 0;
  const allowsRecommendation = eligible && warnings.length === 0;
  return {
    ...item,
    eligibility: item.eligibility
      ? {
          ...item.eligibility,
          eligible,
          hard_failures: hardFailures,
          warnings,
          ruleset_version: "hard-eligibility-v1",
        }
      : null,
    ranking: item.ranking
      ? {
          ...item.ranking,
          recommended:
            allowsRecommendation && Number(item.ranking.final_score) >= 0.6,
          explanation: {
            summary: allowsRecommendation
              ? "저장된 시나리오 관련도 점수와 eligibility gate를 함께 표시합니다."
              : "필수 조건 또는 확인 필요 항목 때문에 관련도 점수와 별개로 추천을 차단했습니다.",
            eligibility_gate: allowsRecommendation ? "allowed" : "blocked",
            hard_failure_codes: hardFailures.map((reason) => reason.code),
            warning_codes: warnings.map((reason) => reason.code),
          },
          ranking_version: "deterministic-baseline-v1",
        }
      : null,
    watched: watchedIds.has(item.id),
  };
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
    input: { source: "packaged synthetic fixture" },
    output: { source_record_id: "control-room-tender" },
    evidence: [{ source_url: "https://example.invalid/lifecycle/control-room/1", synthetic: true }],
    notice: "합성 시나리오 · 외부 네트워크 호출 없음",
  });
  Object.assign(byId.get("dedupe")!, {
    input: { payload_sha256: "committed synthetic fixture" },
    output: {
      duplicate: false,
      dedupe_key: ["synthetic-source", "control-room-tender", "committed-fixture"],
    },
  });
  Object.assign(byId.get("normalize")!, {
    input: { source_record_id: "control-room-tender" },
    output: {
      title: "Synthetic cloud document processing [control-room]",
      lifecycle_stage: "tender",
      estimated_amount: "320000000",
      currency: "KRW",
      regions: ["Seoul"],
    },
    evidence: [{ provenance: "deterministic normalizer snapshot" }],
  });
  Object.assign(byId.get("documents")!, {
    input: { media_type: "text/html" },
    output: {
      parser_kind: "html",
      parser_version: "native-v1",
      page_count: 1,
      text_sha256: "stored in backend replay; omitted from public static snapshot",
    },
  });
  Object.assign(byId.get("ocr-route")!, {
    status: "not_run",
    decision: { route_to_ocr: false },
    notice: "HTML native parsing 품질이 충분해 OCR을 실행하지 않았습니다.",
  });
  Object.assign(byId.get("extract")!, {
    input: { extractor: "deterministic-labels-v1" },
    output: {
      schema_version: "1",
      title: "Synthetic cloud document processing [control-room]",
      buyer_name: "Synthetic Seoul Digital Agency",
      procurement_type: "services",
      estimated_amount: "320000000",
      currency: "KRW",
      published_at: "2026-09-12T00:00:00+00:00",
      closes_at: "2026-10-06T00:00:00+00:00",
      regions: ["Seoul"],
      required_certifications: ["ISO 27001"],
      required_capabilities: ["cloud migration", "document processing"],
    },
    notice: "로컬 deterministic extractor · hosted LLM 호출 없음",
  });
  Object.assign(byId.get("validate")!, {
    input: { schema_version: "1" },
    output: {
      valid: true,
      errors: [],
      trusted_fields: {
        title: "Synthetic cloud document processing [control-room]",
        buyer_name: "Synthetic Seoul Digital Agency",
        procurement_type: "services",
        estimated_amount: "320000000",
        currency: "KRW",
        regions: ["Seoul"],
        required_certifications: ["ISO 27001"],
        required_capabilities: ["cloud migration", "document processing"],
      },
    },
    decision: { trusted: true },
  });
  Object.assign(byId.get("lifecycle")!, {
    input: { stage: "tender" },
    output: { link_state: "initial_tender", official_reference_count: 1 },
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
    input: { watched: false, recommended: true },
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
    input: { source_record_id: "control-room-tender" },
    output: { observed_revision: "control-room-tender", amendment: true },
    evidence: [{ source_url: "https://example.invalid/lifecycle/control-room/2", synthetic: true }],
    notice: "합성 정정 시나리오 · 외부 네트워크 호출 없음",
  });
  Object.assign(byId.get("dedupe")!, {
    input: {
      before_sha256: "committed tender fixture",
      after_sha256: "committed amendment fixture",
    },
    output: { duplicate: false, new_version_required: true },
  });
  Object.assign(byId.get("normalize")!, {
    output: {
      before: {
        title: "Synthetic cloud document processing [control-room]",
        lifecycle_stage: "tender",
        estimated_amount: "320000000",
        currency: "KRW",
        closes_at: "2026-10-06T00:00:00+00:00",
        regions: ["Seoul"],
        required_certifications: ["ISO 27001"],
        required_capabilities: ["cloud migration", "document processing"],
      },
      after: {
        title: "Synthetic cloud document processing [control-room]",
        lifecycle_stage: "amendment",
        estimated_amount: "280000000",
        currency: "KRW",
        closes_at: "2026-09-28T00:00:00+00:00",
        regions: ["Busan"],
        required_certifications: ["ISO 27001"],
        required_capabilities: ["cloud migration", "document processing"],
      },
    },
  });
  Object.assign(byId.get("documents")!, {
    input: { media_type: "text/html" },
    output: {
      parser_kind: "html",
      parser_version: "native-v1",
      page_count: 1,
      text_sha256: "stored in backend replay; omitted from public static snapshot",
    },
  });
  Object.assign(byId.get("ocr-route")!, {
    status: "not_run",
    decision: { route_to_ocr: false },
    notice: "HTML native parsing 경로이므로 OCR은 실행하지 않았습니다.",
  });
  Object.assign(byId.get("extract")!, {
    input: { extractor: "deterministic-labels-v1" },
    output: {
      schema_version: "1",
      title: "Synthetic cloud document processing [control-room]",
      buyer_name: "Synthetic Seoul Digital Agency",
      procurement_type: "services",
      estimated_amount: "280000000",
      currency: "KRW",
      published_at: "2026-09-13T00:00:00+00:00",
      closes_at: "2026-09-28T00:00:00+00:00",
      regions: ["Busan"],
      required_certifications: ["ISO 27001"],
      required_capabilities: ["cloud migration", "document processing"],
    },
    notice: "hosted LLM이 아닌 재현 가능한 로컬 추출 경로입니다.",
  });
  Object.assign(byId.get("validate")!, {
    output: {
      valid: true,
      errors: [],
      trusted_fields: {
        title: "Synthetic cloud document processing [control-room]",
        buyer_name: "Synthetic Seoul Digital Agency",
        procurement_type: "services",
        estimated_amount: "280000000",
        currency: "KRW",
        regions: ["Busan"],
        required_certifications: ["ISO 27001"],
        required_capabilities: ["cloud migration", "document processing"],
      },
    },
    decision: { trusted: true },
  });
  Object.assign(byId.get("lifecycle")!, {
    input: { before_stage: "tender", after_stage: "amendment" },
    output: { same_opportunity: true, version_transition: "tender → amendment" },
    decision: { link_method: "same source record identity" },
  });
  Object.assign(byId.get("delta")!, {
    output: {
      changed_fields: {
        budget: {
          before: { estimated_amount: "320000000", currency: "KRW" },
          after: { estimated_amount: "280000000", currency: "KRW" },
        },
        closes_at: {
          before: "2026-10-06T00:00:00+00:00",
          after: "2026-09-28T00:00:00+00:00",
        },
        regions: { before: ["Seoul"], after: ["Busan"] },
      },
      document_changes: {},
    },
    decision: {
      impact: "high",
      reason_codes: [
        "budget_decreased",
        "deadline_earlier",
        "region_restriction_changed",
      ],
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


const engineeringEvidence: EngineeringEvidence = {
  cpu: {
    status: "measured",
    scope: "cpu_only_production_functions",
    synthetic: true,
    normalized_records: 50000,
    ranked_records: 50000,
    delta_pairs: 5000,
    elapsed_seconds: 6.994830194999963,
    records_per_second: 7148.13635300839,
    limitation:
      "CPU loop only; not PostgreSQL ingest, Redis throughput or SaaS capacity.",
  },
  failure_drill: {
    status: "measured",
    scope: "http_transport_injection",
    cases: [
      { name: "timeout-recovery", attempts: 3, succeeded: true, passed: true },
      { name: "rate-limit-recovery", attempts: 2, succeeded: true, passed: true },
      { name: "server-error-terminal", attempts: 3, succeeded: false, passed: true },
      { name: "forbidden-not-retried", attempts: 1, succeeded: false, passed: true },
    ],
    limitation:
      "Synthetic HTTP failures; sleepers recorded, not actual network/DB outages.",
  },
  release: {
    status: "measured",
    passed: true,
    readiness: "ready",
    gates: [
      { gate: "database-and-redis", passed: true, elapsed_seconds: 9.128632955 },
      { gate: "backend-integration", passed: true, elapsed_seconds: 134.80993098599998 },
      { gate: "full-readiness", passed: true, elapsed_seconds: 2.1315207579999935 },
      { gate: "real-lifecycle-e2e", passed: true, elapsed_seconds: 13.098819434000006 },
      { gate: "pipeline-demo-e2e", passed: true, elapsed_seconds: 9.468859132000034 },
      { gate: "queue-scale", passed: true, elapsed_seconds: 50.98416539200002 },
      { gate: "query-plans", passed: true, elapsed_seconds: 1.6847892979999983 },
      { gate: "http-load", passed: true, elapsed_seconds: 27.555093554999985 },
    ],
    dependencies: {
      database: true,
      schema: true,
      redis: true,
      worker: true,
      scheduler: true,
      storage: true,
      extraction_config: true,
    },
  },
  queue: {
    status: "measured",
    scope: "real_redis_arq_postgresql",
    metrics: {
      records: 1000,
      completed_records: 1000,
      elapsed_seconds: 46.592474568,
      records_per_second: 21.462693477259656,
      successful: true,
      limitation: "Local ingestion only; OCR/external LLM and attachments excluded.",
    },
  },
  http: {
    status: "measured",
    scope: "real_local_http",
    metrics: {
      requests: 200,
      successful_requests: 200,
      failed_requests: 0,
      client_observed_only: true,
      successful: true,
      endpoints: {
        inbox: {
          status: "measured",
          requests: 50,
          concurrency: 5,
          error_count: 0,
          p50_ms: 1159.5945154999754,
          p95_ms: 1219.162342549987,
          requests_per_second: 4.27610158052812,
        },
        search: {
          status: "measured",
          requests: 50,
          concurrency: 5,
          error_count: 0,
          p50_ms: 1154.90500049998,
          p95_ms: 1210.3923193499668,
          requests_per_second: 4.322374359850543,
        },
        detail: {
          status: "measured",
          requests: 50,
          concurrency: 5,
          error_count: 0,
          p50_ms: 165.51361700004463,
          p95_ms: 195.71727990001762,
          requests_per_second: 29.249808926793392,
        },
        admin: {
          status: "measured",
          requests: 50,
          concurrency: 5,
          error_count: 0,
          p50_ms: 25.335382500003334,
          p95_ms: 71.60217759999625,
          requests_per_second: 164.72935934867678,
        },
      },
    },
  },
  query_plans: {
    status: "measured",
    scope: "real_postgresql_explain",
    metrics: {
      records: 1007,
      before: 0.331,
      after: 0.041,
      improvement_ratio: 8.073170731707316,
      candidate_adopted: false,
      candidate_rolled_back: true,
      caution: "Fixed order and warmed caches; repeat across fresh runs before adopting.",
    },
  },
};

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
    const q = normalized(url.searchParams.get("q") ?? "");
    const stage = url.searchParams.get("lifecycle_stage") ?? "";
    const category = normalized(url.searchParams.get("category") ?? "");
    const buyer = normalized(url.searchParams.get("buyer") ?? "");
    const amountMin = Number(url.searchParams.get("amount_min") ?? "");
    const amountMax = Number(url.searchParams.get("amount_max") ?? "");
    const deadlineFrom = Date.parse(url.searchParams.get("deadline_from") ?? "");
    const deadlineTo = Date.parse(url.searchParams.get("deadline_to") ?? "");
    const changedSince = Date.parse(url.searchParams.get("changed_since") ?? "");
    const eligibleOnly = url.searchParams.get("eligible_only") === "true";

    const items = baseOpportunities
      .map(opportunityView)
      .filter(
        (item) =>
          !q ||
          normalized(`${item.title} ${item.buyer_name}`).includes(q),
      )
      .filter((item) => !stage || item.lifecycle_stage === stage)
      .filter(
        (item) =>
          !category || normalized(item.procurement_type ?? "") === category,
      )
      .filter((item) => !buyer || normalized(item.buyer_name).includes(buyer))
      .filter((item) => {
        const amount = item.estimated_amount === null ? NaN : Number(item.estimated_amount);
        if (url.searchParams.has("amount_min")) {
          if (!Number.isFinite(amountMin) || !Number.isFinite(amount) || amount < amountMin) return false;
        }
        if (url.searchParams.has("amount_max")) {
          if (!Number.isFinite(amountMax) || !Number.isFinite(amount) || amount > amountMax) return false;
        }
        return true;
      })
      .filter((item) => {
        const deadline = Date.parse(item.closes_at ?? "");
        if (Number.isFinite(deadlineFrom) && (!Number.isFinite(deadline) || deadline < deadlineFrom))
          return false;
        if (Number.isFinite(deadlineTo) && (!Number.isFinite(deadline) || deadline > deadlineTo))
          return false;
        return true;
      })
      .filter((item) => {
        if (!Number.isFinite(changedSince)) return true;
        const changed = Date.parse(item.changed_at ?? "");
        return Number.isFinite(changed) && changed > changedSince;
      })
      .filter(
        (item) =>
          !eligibleOnly ||
          Boolean(item.eligibility?.eligible && !item.eligibility.warnings.length),
      );
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
    const summary = baseOpportunities.find((candidate) => candidate.id === detailMatch[1]);
    if (!item || !summary) throw new Error("정적 데모 공고를 찾을 수 없습니다.");
    return { ...item, ...opportunityView(summary) };
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

  if (pathname === "/evaluation/engineering-evidence") return engineeringEvidence;

  if (pathname === "/demo/pipeline/scenarios") return staticPipelineScenarios();

  const pipelineScenarioMatch = pathname.match(
    /^\/demo\/pipeline\/scenarios\/([^/]+)$/,
  );
  if (pipelineScenarioMatch)
    return staticPipelineScenario(decodeURIComponent(pipelineScenarioMatch[1]));

  if (pathname === "/admin/pipeline") {
    const pipeline: AdminPipeline = {
      observed_at: now,
      records_fetched_today: baseOpportunities.length,
      new_records_today: baseOpportunities.length,
      changed_versions_today: 1,
      duplicates_skipped_today: 0,
      parsing_failures: 0,
      ocr_fallbacks: 0,
      structured_extraction_count: baseOpportunities.length,
      schema_validation_failures: 0,
      retry_queue_count: 0,
      dlq_count: 0,
      worker_queue_depth: 0,
      scheduler_queue_depth: 0,
      worker_heartbeat: false,
      scheduler_heartbeat: false,
      worker_activity: null,
      scheduler_activity: null,
      parsing: [{ kind: "synthetic_fixture", status: "parsed", count: baseOpportunities.length }],
      extraction: [
        {
          kind: "deterministic_static_snapshot",
          status: "validated",
          count: baseOpportunities.length,
        },
      ],
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