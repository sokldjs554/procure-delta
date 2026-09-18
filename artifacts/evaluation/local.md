# ProcureDelta synthetic evaluation

기계 판독용 원본: `local.json`.

합성 회귀 실험이며 운영 성능/실제 조달 적합도 평가가 아니다. 미실행 지표는 null 또는 not_run이다.

```json
{
  "schema_version": 1,
  "created_at": "2026-09-16T14:27:12.410556+00:00",
  "provenance": {
    "dataset_sha256": "60915644e3d3d36a7aca72a410d40a3075eb472809ed014e50c77f8ecab78116",
    "source_sha256": "68ac6e1e9e144daeba9d2dfffb63152fd14093dc31d4f275557e4ce007266ccc",
    "git_commit": "ba7bba19c5adbdcabbe035a7cf77c4b4e0e03087",
    "git_dirty": true,
    "configuration": {
      "with_ocr": true,
      "hosted": false
    },
    "environment": {
      "python": "3.13.5",
      "os": "Linux-6.18.44-x86_64-with-glibc2.41",
      "cpu_logical_count": 5,
      "machine": "x86_64",
      "cpu_model": "not exposed",
      "shared_sandbox": true
    },
    "synthetic": true
  },
  "dataset_version": "synthetic-v1",
  "public_real_records": 0,
  "extraction_routes": {
    "deterministic": {
      "status": "measured",
      "documents": 10,
      "field_accuracy": 1.0,
      "correct_fields": 30,
      "expected_fields": 30,
      "document_exact_accuracy": 1.0,
      "exact_document_support": 5,
      "date_accuracy": 1.0,
      "date_support": 4,
      "amount_accuracy": 1.0,
      "amount_support": 3,
      "required_conditions": {
        "tp": 5,
        "fp": 0,
        "fn": 0,
        "predicted_support": 5,
        "expected_support": 5,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0
      },
      "rejection_detection": {
        "tp": 5,
        "fp": 0,
        "fn": 0,
        "predicted_support": 5,
        "expected_support": 5,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0
      },
      "schema_violation_rate": 0.4,
      "schema_failures": 4,
      "grounded_accepted_documents": 5,
      "grounded_acceptance_rate": 0.5,
      "hosted_calls": 0,
      "prompt_tokens": null,
      "completion_tokens": null,
      "reported_cost_per_document": null,
      "cost_basis": null,
      "latency_ms": {
        "p50": 0.08165599996345918,
        "p95": 0.5829165499676494
      },
      "rows": [
        {
          "id": "english-full",
          "expected_valid": true,
          "valid": true,
          "schema_valid": true,
          "fields": {
            "correct": 10,
            "expected_fields": 10,
            "accuracy": 1.0,
            "per_field": {
              "title": true,
              "buyer_name": true,
              "procurement_type": true,
              "estimated_amount": true,
              "currency": true,
              "published_at": true,
              "closes_at": true,
              "regions": true,
              "required_certifications": true,
              "required_capabilities": true
            },
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {
            "buyer_name": "Synthetic Agency",
            "title": "Cloud document service",
            "procurement_type": "services",
            "estimated_amount": "125000000",
            "currency": "KRW",
            "published_at": "2026-09-01T00:00:00+00:00",
            "closes_at": "2026-09-30T09:00:00+00:00",
            "regions": [
              "Seoul"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "OCR",
              "cloud migration"
            ]
          },
          "duration_ms": 0.7268719999729001,
          "error_type": null
        },
        {
          "id": "korean-labels",
          "expected_valid": true,
          "valid": true,
          "schema_valid": true,
          "fields": {
            "correct": 9,
            "expected_fields": 9,
            "accuracy": 1.0,
            "per_field": {
              "title": true,
              "buyer_name": true,
              "procurement_type": true,
              "estimated_amount": true,
              "currency": true,
              "published_at": true,
              "closes_at": true,
              "regions": true,
              "required_capabilities": true
            },
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {
            "buyer_name": "합성기관",
            "title": "문서 검색 시스템",
            "procurement_type": "services",
            "estimated_amount": "210000000",
            "currency": "KRW",
            "published_at": "2026-08-31T15:00:00+00:00",
            "closes_at": "2026-09-30T09:00:00+00:00",
            "regions": [
              "Seoul"
            ],
            "required_capabilities": [
              "OCR",
              "Python"
            ]
          },
          "duration_ms": 0.4069709999612314,
          "error_type": null
        },
        {
          "id": "optional-absent",
          "expected_valid": true,
          "valid": true,
          "schema_valid": true,
          "fields": {
            "correct": 3,
            "expected_fields": 3,
            "accuracy": 1.0,
            "per_field": {
              "title": true,
              "buyer_name": true,
              "procurement_type": true
            },
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {
            "buyer_name": "Synthetic Buyer",
            "title": "Only explicit claims",
            "procurement_type": "goods"
          },
          "duration_ms": 0.14386199995897186,
          "error_type": null
        },
        {
          "id": "currency-pair",
          "expected_valid": true,
          "valid": true,
          "schema_valid": true,
          "fields": {
            "correct": 5,
            "expected_fields": 5,
            "accuracy": 1.0,
            "per_field": {
              "title": true,
              "buyer_name": true,
              "procurement_type": true,
              "estimated_amount": true,
              "currency": true
            },
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {
            "buyer_name": "Test Buyer",
            "title": "Synthetic export",
            "procurement_type": "goods",
            "estimated_amount": "1200.5",
            "currency": "USD"
          },
          "duration_ms": 0.13186500001438617,
          "error_type": null
        },
        {
          "id": "qualified-omission",
          "expected_valid": true,
          "valid": true,
          "schema_valid": true,
          "fields": {
            "correct": 3,
            "expected_fields": 3,
            "accuracy": 1.0,
            "per_field": {
              "title": true,
              "buyer_name": true,
              "procurement_type": true
            },
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {
            "buyer_name": "Test Buyer",
            "title": "Unknown requirement",
            "procurement_type": "services"
          },
          "duration_ms": 0.06446500003676192,
          "error_type": null
        },
        {
          "id": "missing-buyer",
          "expected_valid": false,
          "valid": false,
          "schema_valid": false,
          "fields": {
            "correct": 0,
            "expected_fields": 0,
            "accuracy": null,
            "per_field": {},
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {},
          "duration_ms": 0.06607799997482289,
          "error_type": null
        },
        {
          "id": "invalid-deadline",
          "expected_valid": false,
          "valid": false,
          "schema_valid": false,
          "fields": {
            "correct": 0,
            "expected_fields": 0,
            "accuracy": null,
            "per_field": {},
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {},
          "duration_ms": 0.06196099997168858,
          "error_type": null
        },
        {
          "id": "contradictory-money",
          "expected_valid": false,
          "valid": false,
          "schema_valid": true,
          "fields": {
            "correct": 0,
            "expected_fields": 0,
            "accuracy": null,
            "per_field": {},
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {},
          "duration_ms": 0.09723399995209547,
          "error_type": null
        },
        {
          "id": "zero-money",
          "expected_valid": false,
          "valid": false,
          "schema_valid": false,
          "fields": {
            "correct": 0,
            "expected_fields": 0,
            "accuracy": null,
            "per_field": {},
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {},
          "duration_ms": 0.04742999999507447,
          "error_type": null
        },
        {
          "id": "unstructured-prose",
          "expected_valid": false,
          "valid": false,
          "schema_valid": false,
          "fields": {
            "correct": 0,
            "expected_fields": 0,
            "accuracy": null,
            "per_field": {},
            "missing": [],
            "unexpected": [],
            "exact_match": true
          },
          "trusted_fields": {},
          "duration_ms": 0.019269000006261194,
          "error_type": null
        }
      ]
    },
    "hosted_all": {
      "status": "not_run",
      "reason": "explicit hosted opt-in not supplied",
      "metrics": null
    },
    "hosted_gated": {
      "status": "not_run",
      "reason": "explicit hosted opt-in not supplied",
      "metrics": null
    }
  },
  "ocr": {
    "status": "measured",
    "provider": "tesseract 5.5.0",
    "language": "eng",
    "synthetic": true,
    "images": 3,
    "actual_recognition_invocations": 1,
    "elapsed_ms": 270.8216490000268,
    "correct_fields": 17,
    "expected_fields": 18,
    "field_accuracy": 0.9444444444444444,
    "rows": [
      {
        "id": "clean",
        "recognition_text": "Title: Synthetic cloud project\nBuyer: Example Agency\nCategory: services\n\nBudget: KRW 125000000\nRegion: Seoul",
        "field_metrics": {
          "correct": 6,
          "expected_fields": 6,
          "accuracy": 1.0,
          "per_field": {
            "title": true,
            "buyer_name": true,
            "procurement_type": true,
            "estimated_amount": true,
            "currency": true,
            "regions": true
          },
          "missing": [],
          "unexpected": [],
          "exact_match": true
        },
        "downstream_valid": true
      },
      {
        "id": "blurred",
        "recognition_text": "Title: Synthetic cloud project\nBuyer: Example Agency\nCategory: services\n\nBudget: KRW 125000000\nRegion: Seoul",
        "field_metrics": {
          "correct": 6,
          "expected_fields": 6,
          "accuracy": 1.0,
          "per_field": {
            "title": true,
            "buyer_name": true,
            "procurement_type": true,
            "estimated_amount": true,
            "currency": true,
            "regions": true
          },
          "missing": [],
          "unexpected": [],
          "exact_match": true
        },
        "downstream_valid": true
      },
      {
        "id": "low_resolution",
        "recognition_text": "Title: Synthetic cloud project\nBuyer: Example Agency\nCategory: services\n\nBudget: KRW 125000000\nReglor: Seoul",
        "field_metrics": {
          "correct": 5,
          "expected_fields": 6,
          "accuracy": 0.8333333333333334,
          "per_field": {
            "title": true,
            "buyer_name": true,
            "procurement_type": true,
            "estimated_amount": true,
            "currency": true,
            "regions": false
          },
          "missing": [
            "regions"
          ],
          "unexpected": [],
          "exact_match": false
        },
        "downstream_valid": true
      }
    ],
    "limitation": "English rendered images only; not Korean scans, layouts or production OCR."
  },
  "lifecycle": {
    "cases": 5,
    "links": {
      "tp": 2,
      "fp": 0,
      "fn": 0,
      "predicted_support": 2,
      "expected_support": 2,
      "precision": 1.0,
      "recall": 1.0,
      "f1": 1.0
    },
    "rows": [
      {
        "id": "official",
        "parent": 1,
        "expected_parent": 1,
        "status": "resolved",
        "reason": null
      },
      {
        "id": "ambiguous",
        "parent": null,
        "expected_parent": null,
        "status": "unresolved",
        "reason": "ambiguous_official_reference"
      },
      {
        "id": "missing",
        "parent": null,
        "expected_parent": null,
        "status": "unresolved",
        "reason": "official_reference_not_found"
      },
      {
        "id": "reverse-stage",
        "parent": null,
        "expected_parent": null,
        "status": "unresolved",
        "reason": "incompatible_stage"
      },
      {
        "id": "fingerprint",
        "parent": 1,
        "expected_parent": 1,
        "status": "resolved",
        "reason": null
      }
    ]
  },
  "delta": {
    "cases": 8,
    "fields": {
      "tp": 7,
      "fp": 0,
      "fn": 0,
      "predicted_support": 7,
      "expected_support": 7,
      "precision": 1.0,
      "recall": 1.0,
      "f1": 1.0
    },
    "high_impact": {
      "tp": 4,
      "fp": 0,
      "fn": 0,
      "predicted_support": 4,
      "expected_support": 4,
      "precision": 1.0,
      "recall": 1.0,
      "f1": 1.0
    },
    "false_alert_rate": 0.0,
    "no_change_support": 2,
    "rows": [
      {
        "id": "no-change",
        "fields": [],
        "impact": "low",
        "expected_fields": [],
        "expected_impact": "low"
      },
      {
        "id": "budget",
        "fields": [
          "budget"
        ],
        "impact": "medium",
        "expected_fields": [
          "budget"
        ],
        "expected_impact": "medium"
      },
      {
        "id": "deadline-earlier",
        "fields": [
          "closes_at"
        ],
        "impact": "high",
        "expected_fields": [
          "closes_at"
        ],
        "expected_impact": "high"
      },
      {
        "id": "region-change",
        "fields": [
          "regions"
        ],
        "impact": "high",
        "expected_fields": [
          "regions"
        ],
        "expected_impact": "high"
      },
      {
        "id": "cert-added",
        "fields": [
          "required_certifications"
        ],
        "impact": "high",
        "expected_fields": [
          "required_certifications"
        ],
        "expected_impact": "high"
      },
      {
        "id": "format-only",
        "fields": [],
        "impact": "low",
        "expected_fields": [],
        "expected_impact": "low"
      },
      {
        "id": "capability-removed",
        "fields": [
          "required_capabilities"
        ],
        "impact": "medium",
        "expected_fields": [
          "required_capabilities"
        ],
        "expected_impact": "medium"
      },
      {
        "id": "compound",
        "fields": [
          "budget",
          "regions"
        ],
        "impact": "high",
        "expected_fields": [
          "budget",
          "regions"
        ],
        "expected_impact": "high"
      }
    ]
  },
  "eligibility": {
    "tp": 5,
    "fp": 0,
    "fn": 0,
    "predicted_support": 5,
    "expected_support": 5,
    "precision": 1.0,
    "recall": 1.0,
    "f1": 1.0,
    "false_positive_hard_eligibility_rate": 0.0,
    "hard_negative_support": 5
  },
  "historical_replay": [
    {
      "as_of": "2026-09-03T00:00:00+00:00",
      "profile_id": "profile-before",
      "profile_available_at": "2026-08-01T00:00:00Z",
      "decisions": [
        {
          "record_id": "A",
          "version_id": "A-1",
          "fields": {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": [
              "Seoul"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "OCR"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "cloud migration OCR",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-01T00:00:00Z",
          "observed_at": "2026-09-02T00:00:00Z",
          "created_at": "2026-09-02T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": true,
          "hard_failure_codes": [],
          "warning_codes": [],
          "score": 0.89938,
          "recommended": true,
          "features": {
            "lexical": "1.00000",
            "capability": "1.00000",
            "category": "1.00000",
            "amount": "0.66667",
            "recency_deadline": "0.66250"
          }
        },
        {
          "record_id": "C",
          "version_id": "C-1",
          "fields": {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": [
              "Busan"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "OCR"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "cloud migration OCR",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-01T00:00:00Z",
          "observed_at": "2026-09-02T00:00:00Z",
          "created_at": "2026-09-02T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": false,
          "hard_failure_codes": [
            "region_not_served"
          ],
          "warning_codes": [],
          "score": 0.89938,
          "recommended": false,
          "features": {
            "lexical": "1.00000",
            "capability": "1.00000",
            "category": "1.00000",
            "amount": "0.66667",
            "recency_deadline": "0.66250"
          }
        },
        {
          "record_id": "B",
          "version_id": "B-1",
          "fields": {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": [
              "Seoul"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "woodworking"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "office furniture",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-01T00:00:00Z",
          "observed_at": "2026-09-02T00:00:00Z",
          "created_at": "2026-09-02T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": true,
          "hard_failure_codes": [],
          "warning_codes": [],
          "score": 0.46188,
          "recommended": false,
          "features": {
            "lexical": "0.25000",
            "capability": "0.00000",
            "category": "1.00000",
            "amount": "0.66667",
            "recency_deadline": "0.66250"
          }
        }
      ],
      "ranked_ids": [
        "A",
        "B"
      ],
      "outcome_features_used": false,
      "metrics": {
        "k": 2,
        "returned": 2,
        "hits": 2,
        "relevant_support": 2,
        "recall_at_k": 1.0,
        "ndcg_at_k": 1.0
      },
      "expected_allowed": [
        "A",
        "B"
      ]
    },
    {
      "as_of": "2026-09-10T00:00:00+00:00",
      "profile_id": "profile-before",
      "profile_available_at": "2026-08-01T00:00:00Z",
      "decisions": [
        {
          "record_id": "A",
          "version_id": "A-2",
          "fields": {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": [
              "Busan"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "OCR"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "cloud migration OCR",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-08T00:00:00Z",
          "observed_at": "2026-09-09T00:00:00Z",
          "created_at": "2026-09-09T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": false,
          "hard_failure_codes": [
            "region_not_served"
          ],
          "warning_codes": [],
          "score": 0.89354,
          "recommended": false,
          "features": {
            "lexical": "1.00000",
            "capability": "1.00000",
            "category": "1.00000",
            "amount": "0.66667",
            "recency_deadline": "0.62361"
          }
        },
        {
          "record_id": "C",
          "version_id": "C-1",
          "fields": {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": [
              "Busan"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "OCR"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "cloud migration OCR",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-01T00:00:00Z",
          "observed_at": "2026-09-02T00:00:00Z",
          "created_at": "2026-09-02T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": false,
          "hard_failure_codes": [
            "region_not_served"
          ],
          "warning_codes": [],
          "score": 0.89354,
          "recommended": false,
          "features": {
            "lexical": "1.00000",
            "capability": "1.00000",
            "category": "1.00000",
            "amount": "0.66667",
            "recency_deadline": "0.62361"
          }
        },
        {
          "record_id": "B",
          "version_id": "B-1",
          "fields": {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": [
              "Seoul"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "woodworking"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "office furniture",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-01T00:00:00Z",
          "observed_at": "2026-09-02T00:00:00Z",
          "created_at": "2026-09-02T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": true,
          "hard_failure_codes": [],
          "warning_codes": [],
          "score": 0.45604,
          "recommended": false,
          "features": {
            "lexical": "0.25000",
            "capability": "0.00000",
            "category": "1.00000",
            "amount": "0.66667",
            "recency_deadline": "0.62361"
          }
        }
      ],
      "ranked_ids": [
        "B"
      ],
      "outcome_features_used": false,
      "metrics": {
        "k": 2,
        "returned": 1,
        "hits": 1,
        "relevant_support": 1,
        "recall_at_k": 1.0,
        "ndcg_at_k": 1.0
      },
      "expected_allowed": [
        "B"
      ]
    },
    {
      "as_of": "2026-09-16T00:00:00+00:00",
      "profile_id": "profile-before",
      "profile_available_at": "2026-08-01T00:00:00Z",
      "decisions": [
        {
          "record_id": "D",
          "version_id": "D-1",
          "fields": {
            "estimated_amount": "110",
            "currency": "KRW",
            "regions": [
              "Seoul"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "OCR"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "cloud migration OCR",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-01T00:00:00Z",
          "observed_at": "2026-09-15T00:00:00Z",
          "created_at": "2026-09-15T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": true,
          "hard_failure_codes": [],
          "warning_codes": [],
          "score": 0.90854,
          "recommended": true,
          "features": {
            "lexical": "1.00000",
            "capability": "1.00000",
            "category": "1.00000",
            "amount": "0.80000",
            "recency_deadline": "0.59028"
          }
        },
        {
          "record_id": "A",
          "version_id": "A-2",
          "fields": {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": [
              "Busan"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "OCR"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "cloud migration OCR",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-08T00:00:00Z",
          "observed_at": "2026-09-09T00:00:00Z",
          "created_at": "2026-09-09T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": false,
          "hard_failure_codes": [
            "region_not_served"
          ],
          "warning_codes": [],
          "score": 0.88854,
          "recommended": false,
          "features": {
            "lexical": "1.00000",
            "capability": "1.00000",
            "category": "1.00000",
            "amount": "0.66667",
            "recency_deadline": "0.59028"
          }
        },
        {
          "record_id": "C",
          "version_id": "C-1",
          "fields": {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": [
              "Busan"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "OCR"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "cloud migration OCR",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-01T00:00:00Z",
          "observed_at": "2026-09-02T00:00:00Z",
          "created_at": "2026-09-02T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": false,
          "hard_failure_codes": [
            "region_not_served"
          ],
          "warning_codes": [],
          "score": 0.88854,
          "recommended": false,
          "features": {
            "lexical": "1.00000",
            "capability": "1.00000",
            "category": "1.00000",
            "amount": "0.66667",
            "recency_deadline": "0.59028"
          }
        },
        {
          "record_id": "B",
          "version_id": "B-1",
          "fields": {
            "estimated_amount": "100",
            "currency": "KRW",
            "regions": [
              "Seoul"
            ],
            "required_certifications": [
              "ISO 27001"
            ],
            "required_capabilities": [
              "woodworking"
            ],
            "closes_at": "2026-09-30T09:00:00+00:00",
            "title": "office furniture",
            "buyer_name": "Synthetic Agency",
            "procurement_type": "services",
            "published_at": "2026-09-01T00:00:00Z"
          },
          "effective_at": "2026-09-01T00:00:00Z",
          "observed_at": "2026-09-02T00:00:00Z",
          "created_at": "2026-09-02T00:00:00Z",
          "extraction_id": null,
          "allows_recommendation": true,
          "hard_failure_codes": [],
          "warning_codes": [],
          "score": 0.45104,
          "recommended": false,
          "features": {
            "lexical": "0.25000",
            "capability": "0.00000",
            "category": "1.00000",
            "amount": "0.66667",
            "recency_deadline": "0.59028"
          }
        }
      ],
      "ranked_ids": [
        "D",
        "B"
      ],
      "outcome_features_used": false,
      "metrics": {
        "k": 2,
        "returned": 2,
        "hits": 2,
        "relevant_support": 2,
        "recall_at_k": 1.0,
        "ndcg_at_k": 1.0
      },
      "expected_allowed": [
        "B",
        "D"
      ]
    }
  ],
  "total_elapsed_ms": 315.4507220000369,
  "limitations": [
    "Tiny hand-authored synthetic regression set, not unseen real procurement data.",
    "Labels authored for this system, so these are smoke/regression scores, not generalization.",
    "Outcome labels are not features and do not independently prove company suitability.",
    "Local OCR benchmark is separate from the default service fixture-fake OCR adapter.",
    "Timings exclude live network, PostgreSQL, Redis and end-user request latency."
  ]
}
```
