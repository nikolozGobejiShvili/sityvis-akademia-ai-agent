# Graph Report - app  (2026-07-27)

## Corpus Check
- 91 files · ~233,677 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 2582 nodes · 5350 edges · 146 communities (138 shown, 8 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 305 edges (avg confidence: 0.7)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `c92ff438`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- _handle_core
- load_knowledge
- ParentToolExecutor
- _ensure_lead
- camp_topic_facts.py
- timedelta
- conversation_planner.py
- has_value
- run_parent_llm_turn
- pending_workflow.py
- conversation_service.py
- parent_turn_analyzer.py
- admin.py
- Lead
- webhook.py
- program_resolver.py
- adult_tool_executor.py
- conversation_trace.py
- decision/__init__.py
- _clean_challenge_for_email
- openai_service.py
- parent_reply_composer.py
- adult_flow.py
- _apply_client_emoji_policy
- Conversation
- Settings
- models.py
- ProgramId
- history
- redis_state_service.py
- calendar_service.py
- context_arbiter.py
- parent_turn_router.py
- Any
- followup_service.py
- parent_llm_engine.py
- .from_dict
- FlowContext
- _maybe_handle_camp_intro
- conversation_act.py
- get_section
- _maybe_handle_event_inquiry
- response_policy.py
- Adult sales policy — სიტყვის აკადემია
- config.py
- run_adult_llm_turn
- _maybe_handle_availability_question
- _response_for_intent
- .get
- admin_config_service.py
- get_active_adult_events
- sheets_service.py
- approved_copy_service.py
- _load_adult_events_raw
- adult_llm_engine.py
- find_events_by_reference
- Parent sales policy — სიტყვის აკადემია
- template_loader.py
- Enum
- adult_subscription_service.py
- sentry_service.py
- _build_sales_context
- conversation.py
- _reasoning_reflect
- comment_service.py
- determine_segment_from_post
- _maybe_handle_subscription
- _child_age_known
- _capture_turn_facts
- _parse_booking_datetime
- build_section_dm
- _conversation_has_assistant_turn
- _maybe_handle_named_adult_event
- detect_legacy_explicit_action
- send_dm_from_comment
- _load_conversation_from_redis
- MessengerService
- selected_state.py
- sanitise_adult_response
- clean_challenge_for_storage
- _suppress_redundant_age_question
- reserved_program_ids
- PARENT communication style — სიტყვის აკადემია
- _events_matching_text
- learning_log_service.py
- skills_service.py
- _maybe_adult_offtopic_reply
- maybe_handle_analyzer_interrupt
- get_adult_events
- adult_event_broadcast_service.py
- find_approved_answer
- detect_parent_interrupt_intent
- .is_whatsapp_configured
- _build_active_events_list_block
- _build_parent_rich_dm
- kill_switch.py
- _apply_safe_fields
- canonical_session_key
- _build_system_prompt
- _ensure_adult_intro_followup
- time
- _build_slim_context
- _mark_subscription_offer_if_present
- load_google_credentials
- parent_flow.py
- _planner_pre_answer
- main.py
- _send_email
- _build_sunday_school_comment_dm
- _has_adult_events_configured
- _meta_error_summary
- _classify_segment
- README.md
- adult_tools.py
- tools/__init__.py
- parent_tools.py
- lead_memory_service.py
- reasoning/__init__.py
- _record_pending_booking_for_slot
- _BusyCalendarQueryError
- get_active_sections
- to_tbilisi
- FollowupService
- ExternalEmailDeliveryBlocked

## God Nodes (most connected - your core abstractions)
1. `Conversation` - 184 edges
2. `Lead` - 118 edges
3. `_handle_core()` - 61 edges
4. `Settings` - 51 edges
5. `run_parent_llm_turn()` - 34 edges
6. `run_adult_llm_turn()` - 32 edges
7. `_IdentityMatch` - 31 edges
8. `ParentToolExecutor` - 30 edges
9. `NormalizedMessage` - 30 edges
10. `ProgramId` - 28 edges

## Surprising Connections (you probably didn't know these)
- `_classify_done_event()` --calls--> `detect_parent_interrupt_intent()`  [INFERRED]
  app/flows/parent_flow.py → app/agent/intent/parent_intent_detector.py
- `maybe_handle_analyzer_interrupt()` --calls--> `detect_parent_interrupt_intent()`  [INFERRED]
  app/flows/parent_turn_router.py → app/agent/intent/parent_intent_detector.py
- `maybe_handle_pending_booking_continuation()` --calls--> `detect_parent_interrupt_intent()`  [INFERRED]
  app/flows/parent_turn_router.py → app/agent/intent/parent_intent_detector.py
- `_last_assistant_was_subscription_offer()` --indirect_call--> `history()`  [INFERRED]
  app/agent/llm/adult_llm_engine.py → app/reasoning/conversation_trace.py
- `_deterministic_subscribe()` --calls--> `AdultToolExecutor`  [INFERRED]
  app/agent/llm/adult_llm_engine.py → app/agent/tools/adult_tool_executor.py

## Import Cycles
- None detected.

## Communities (146 total, 8 thin omitted)

### Community 0 - "_handle_core"
Cohesion: 0.05
Nodes (47): _camp_off_suppresses_info(), _dedupe_child_age_questions(), _ensure_adult_intro_followup_for_parent_flow(), _ensure_camp_age_question(), _format_multipoint_paragraphs(), _handle_core(), _is_active_per_product_booking(), _is_thanks_or_farewell_close() (+39 more)

### Community 1 - "load_knowledge"
Cohesion: 0.15
Nodes (14): KnowledgeNotFound, load_knowledge(), _path_for(), Any, FileNotFoundError, Path, Knowledge / business-fact loader.  Loads structured YAML knowledge files from ``, Raised when a named knowledge file is missing or malformed. (+6 more)

### Community 2 - "ParentToolExecutor"
Cohesion: 0.14
Nodes (15): _camp_public_info_limited_tool_result(), ParentToolExecutor, Any, Pull alternatives for the same date the user named, fall back         to the le, P3-C PATCH 1 — cancel or reschedule an existing booking.          The executor, Executes the closed-set of tools the PARENT LLM is allowed to call.      One i, P3-C PATCH 1 — flip the conversation segment so the next         inbound messag, JSON-dump with ensure_ascii=False so Georgian text round-trips. (+7 more)

### Community 3 - "_ensure_lead"
Cohesion: 0.04
Nodes (77): _bot_recently_asked_for_contact(), _build_state_recall_reply(), _capture_contact_and_ask_time(), _clear_stale_pending_datetime(), _confirmed_pending_iso(), _distinct_valid_phones(), _ensure_lead(), _extract_corrected_name() (+69 more)

### Community 4 - "camp_topic_facts.py"
Cohesion: 0.07
Nodes (59): answer_for_topic(), _canonical_overview_facts(), _count(), detect_camp_topic(), direct_call_fallback(), _eligibility_line(), _extract_any_age(), _extract_eligible_age() (+51 more)

### Community 5 - "timedelta"
Cohesion: 0.16
Nodes (18): apply_colloquial_time_to_iso(), extract_colloquial_hour(), _extract_half_hour(), _extract_spelled_hour(), format_tbilisi_datetime(), _normalize_pm_hour(), now_tbilisi(), now_tbilisi_iso() (+10 more)

### Community 6 - "conversation_planner.py"
Cohesion: 0.06
Nodes (49): _booked(), _camp_subintent(), _context_was_closed(), _has_camp_concern(), _has_camp_signal(), _is_adult_age_self_statement(), _is_affirmation_like(), _is_greeting_only() (+41 more)

### Community 7 - "has_value"
Cohesion: 0.25
Nodes (5): _format_phone_display(), book_slot(), _build_event_description(), _build_event_title(), CalendarService

### Community 8 - "run_parent_llm_turn"
Cohesion: 0.06
Nodes (56): _apply_offtopic_intelligence(), _approved_answer_prompt_suffix(), _assistant_message_for_tool_calls(), build_active_tools(), _build_context_message(), _build_slim_context(), _build_system_prompt(), _choice_message() (+48 more)

### Community 9 - "pending_workflow.py"
Cohesion: 0.11
Nodes (42): ExpectedReplyKind, NormalizedMessage, _pending_snapshot_sort_key(), PendingWorkflowAction, PendingWorkflowDecision, PendingWorkflowError, PendingWorkflowPolicy, PendingWorkflowReason (+34 more)

### Community 10 - "conversation_service.py"
Cohesion: 0.06
Nodes (43): classify_outcome(), Any, Pure outcome classifier for Phase 5 (bounded, human-gated learning).  Classifies, _apply_response_policy(), _extract_template_section(), get_all_conversations_snapshot(), _handle_subscription_request(), _handle_subscription_save() (+35 more)

### Community 11 - "parent_turn_analyzer.py"
Cohesion: 0.09
Nodes (41): analyze_for_engine(), analyze_parent_turn(), _analyzer_enabled(), build_payload(), _build_reasoning_user_payload(), _coerce_confidence(), _coerce_fact_types(), _coerce_provided_fields() (+33 more)

### Community 12 - "admin.py"
Cohesion: 0.08
Nodes (38): HTTPBasicCredentials, activate_adult_event_route(), admin_dashboard(), admin_dashboard_slash(), create_adult_event(), create_program(), deactivate_adult_event_route(), edit_adult_event_form() (+30 more)

### Community 13 - "Lead"
Cohesion: 0.07
Nodes (57): Client, has_value(), EmailMessage, Lead, _adult_detail_lines(), _booking_text(), _build_adult_summary(), _build_email_subject() (+49 more)

### Community 14 - "webhook.py"
Cohesion: 0.10
Nodes (36): BackgroundTasks, PlainTextResponse, _candidate_app_secrets(), _dispatch_buffered_reply(), _dm_already_seen(), _dm_dedup_key(), _extract_messages(), _extract_meta_messages() (+28 more)

### Community 15 - "program_resolver.py"
Cohesion: 0.13
Nodes (36): ProgramMention, ProgramMentionRole, ProgramResolutionPolicy, One bounded current-message mention of a canonical program., Single immutable owner of bounded human-language program rules., Closed semantic roles for a current-message program mention., _assign_roles(), _best_identity_match_at() (+28 more)

### Community 16 - "adult_tool_executor.py"
Cohesion: 0.10
Nodes (21): _adult_manager_notified_redis_key(), AdultToolExecutor, _is_adult_manager_notified(), _mark_adult_manager_notified(), mark_price_disclosed(), mark_sold_out_disclosed(), mark_subscription_confirmed(), _mask_phone() (+13 more)

### Community 17 - "conversation_trace.py"
Cohesion: 0.09
Nodes (26): active(), begin(), emit(), _enabled(), _mask_identifier(), _mask_session_key(), Per-turn diagnostic trace (Phase 3, 2026-06-24). Observability ONLY — no behavio, Merge safe RouteDecision fields into the current trace block.      Observability (+18 more)

### Community 18 - "decision/__init__.py"
Cohesion: 0.11
Nodes (30): Stable public API for program identity and registry metadata., derive_conservative_token_form(), _distance_limit(), _levenshtein_distance(), match_curated_token(), normalize_message(), Pure, deterministic preprocessing for inbound message text., Build immutable non-semantic representations of raw inbound text. (+22 more)

### Community 19 - "_clean_challenge_for_email"
Cohesion: 0.20
Nodes (12): _canonicalise_goal(), _clause_is_question(), _clean_challenge_for_email(), _dedupe_repeated_phrase(), _extract_additional_question(), Collapse a doubled phrase. Returns the input unchanged when no     obvious doubl, Split a raw challenge string into clauses on commas / semicolons     and the con, Normalise a few noisy goal variants. Unknown goals pass through     untouched (w (+4 more)

### Community 20 - "openai_service.py"
Cohesion: 0.10
Nodes (32): analyze_parent_turn(), _build_completion_kwargs(), _build_system_prompt(), _chat_completion(), chat_with_tools(), _client(), compose_reply(), detect_segment() (+24 more)

### Community 21 - "parent_reply_composer.py"
Cohesion: 0.09
Nodes (33): build_payload(), _build_post_booking_payload(), compose_parent_reply(), compose_post_booking_response(), _composer_enabled(), _detect_hallucinated_fact(), _format_knowledge_block(), _lead_field() (+25 more)

### Community 22 - "adult_flow.py"
Cohesion: 0.13
Nodes (31): _admin_event_to_flow_event(), _booking_question(), _clear_selected_event(), _current_event(), _detect_event(), _end_with_booking_question(), _ensure_lead(), _event_context() (+23 more)

### Community 23 - "_apply_client_emoji_policy"
Cohesion: 0.08
Nodes (31): _add_heart_after_first_sentence(), _add_heart_after_greeting(), _apply_client_emoji_policy(), apply_greeting_farewell_heart(), _bot_has_replied(), handle(), _has_any_child_age_question(), _normalise_agixsnit_wording() (+23 more)

### Community 24 - "Conversation"
Cohesion: 0.05
Nodes (58): _apply_privacy_notice_policy(), _attempt_booking(), _book_selected_slot(), _booking_success_this_turn(), _compose_or_fallback(), _detect_safe_intent(), _end_with_consultation_offer(), _exact_detail_already_general() (+50 more)

### Community 26 - "models.py"
Cohesion: 0.13
Nodes (22): _program_mention_sort_key(), ProgramIdentityDefinition, ProgramPhraseRule, ProgramResolutionDecision, ProgramResolutionError, ProgramStemRule, ProgramTokenRule, Immutable domain types for the program registry. (+14 more)

### Community 27 - "ProgramId"
Cohesion: 0.13
Nodes (21): ProgramDefinition, ProgramId, ProgramOwnerReferences, Canonical program identifiers., An exact, already-canonical alias for one program., A symbolic reference to an existing owner, never a runtime object., Symbolic source owners associated with a program., Stable program identity and symbolic ownership metadata. (+13 more)

### Community 28 - "history"
Cohesion: 0.07
Nodes (34): _assistant_gave_camp_price(), _bot_in_manager_handoff_collection(), _bot_in_sunday_school_collection(), _bot_last_gave_payment_method_answer(), _bot_last_reply_asked_for_contact(), _bot_last_reply_asked_for_name(), _bot_recently_asked_challenge_question(), _bot_recently_gave_sports_answer() (+26 more)

### Community 29 - "redis_state_service.py"
Cohesion: 0.12
Nodes (28): _conversation_ttl(), conversation_ttl_seconds(), delete(), _ensure_client(), exists(), get_json(), is_enabled(), log_startup_status() (+20 more)

### Community 30 - "calendar_service.py"
Cohesion: 0.17
Nodes (25): _booked_ranges(), _calendar_service(), cancel_calendar_event(), check_slot_available(), check_slot_calendar_only(), create_event(), _event_datetime(), _format_options() (+17 more)

### Community 31 - "context_arbiter.py"
Cohesion: 0.15
Nodes (23): arbitrate_context(), _candidate_sort_key(), _consolidate_candidates(), _contains_phrase(), _decision(), _has_context_reset(), _is_fresh(), _is_structurally_elliptical() (+15 more)

### Community 32 - "parent_turn_router.py"
Cohesion: 0.13
Nodes (22): _build_cancel_response(), _build_identity_answer(), _build_manager_ask_phone(), _build_manager_handoff_with_phone(), _build_pending_ask_contact(), _build_pending_ask_name(), _build_pending_ask_phone(), _build_pending_invalid_phone() (+14 more)

### Community 33 - "Any"
Cohesion: 0.12
Nodes (27): delete_section(), find_section_by_hashtag(), find_section_from_comment_text(), find_section_from_post_hashtags(), find_section_from_post_id(), load_business_hours_mirror(), load_manager_contacts_mirror(), load_sections() (+19 more)

### Community 34 - "followup_service.py"
Cohesion: 0.14
Nodes (22): check_and_send_followups(), _effective_cadence(), _first_delay(), _followup_context(), _followup_message(), _maybe_send_followup_for_conversation(), _parse_last_bot_message_at(), _pick_due_cadence() (+14 more)

### Community 35 - "parent_llm_engine.py"
Cohesion: 0.15
Nodes (13): _apply_dynamic_fact_normalisations(), _camp_age_bounds_safe(), _collapse_duplicated_tu(), _is_concern_preamble_sentence(), _is_known_about_you_preamble(), Lean Sanitizer mode (Phase 4, Task 4). When ON, `sanitise_response_wording`, Remove the awkward „შეშფოთება" / „info already known about age &     concern" p, Canonical camp age band for the sanitizer's fact-aware rewrite.      Reads the (+5 more)

### Community 36 - ".from_dict"
Cohesion: 0.28
Nodes (5): _parse_iso_or_now(), Any, datetime, Reconstruct a Lead from a ``model_dump(mode="json")`` payload.          Symmetri, Best-effort ISO-string → datetime, falling back to ``utcnow``.

### Community 37 - "FlowContext"
Cohesion: 0.29
Nodes (3): _flow_context(), FlowContext, _segment_tone()

### Community 38 - "_maybe_handle_camp_intro"
Cohesion: 0.09
Nodes (25): _answer_camp_part(), _camp_price_question_count(), _camp_price_value(), _final_camp_policy_has_recent_camp_context(), _is_camp_price_intent(), _is_mixed_camp_adult_request(), _is_payment_question(), _is_self_overage_camp_request() (+17 more)

### Community 39 - "conversation_act.py"
Cohesion: 0.18
Nodes (21): _contains_any_phrase(), _contains_phrase(), _decision(), _has_stem(), _is_callback(), _is_correction(), _is_exact_phrase(), _is_greeting() (+13 more)

### Community 40 - "get_section"
Cohesion: 0.09
Nodes (24): get_camp_age_bounds(), get_camp_facts(), get_camp_registration_status(), get_manager_phone(), get_program_age_bounds(), get_section(), get_sunday_school_status(), get_visible_camp_streams() (+16 more)

### Community 41 - "_maybe_handle_event_inquiry"
Cohesion: 0.07
Nodes (35): _apply_booking_translit(), _bot_recently_asked_booking_datetime(), _bot_recently_listed_events(), _detect_daypart(), _event_link(), _extract_event_day_reference(), _format_event_price_for_inquiry(), _in_consultation_booking_context() (+27 more)

### Community 42 - "response_policy.py"
Cohesion: 0.10
Nodes (19): _age_bounds(), _camp_facts(), camp_info_opener(), camp_price_answer(), collapse_repeated_thanks(), eligible_age_reply(), fix_consultation_cta(), neutral_menu() (+11 more)

### Community 43 - "Adult sales policy — სიტყვის აკადემია"
Cohesion: 0.10
Nodes (20): 10. Tone, 11. Grammar, 12. Scope rule (off-topic), 13. Future verticals, 1. Role, 2. Conversation principle, 3.1 Age memory (CRITICAL invariant), 3.2 child_age leakage rule (CRITICAL) (+12 more)

### Community 44 - "config.py"
Cohesion: 0.19
Nodes (18): ConfigurationError, _env(), get_settings(), _load_text_file(), _parse_bool_optional(), _parse_csv(), _parse_float_safe(), _parse_followup_hours() (+10 more)

### Community 45 - "run_adult_llm_turn"
Cohesion: 0.16
Nodes (20): _assistant_message_for_tool_calls(), _build_system_prompt(), _choice_message(), _first_choice(), _message_content(), _parse_tool_args(), Any, Run one ADULT turn through the LLM engine.      Returns the final assistant te (+12 more)

### Community 46 - "_maybe_handle_availability_question"
Cohesion: 0.07
Nodes (34): _age_status_for_lead(), _camp_age_bounds(), _ensure_ineligible_young_age_message(), _format_handoff_paragraphs(), _format_next_free_slots(), _free_slots_for_date_safe(), _join_georgian(), _maybe_handle_availability_question() (+26 more)

### Community 47 - "_response_for_intent"
Cohesion: 0.13
Nodes (20): _build_no_concern_answer(), _build_out_of_scope_answer(), _build_premium_conditions_answer(), _build_premium_dates_answer(), _build_premium_location_answer(), _build_premium_registration_answer(), _camp(), _camp_registration_closed_answer() (+12 more)

### Community 48 - ".get"
Cohesion: 0.22
Nodes (7): Formatter, ContentRepository, _ConversationStore, Any, dict, In-memory store keyed by canonical session key.      Existing tests and a few, SafeFormatter

### Community 49 - "admin_config_service.py"
Cohesion: 0.12
Nodes (24): _backup(), build_section_dm(), _config_read_path(), _dump_yaml(), _ensure_admin_config_dir(), get_template(), load_templates(), _locative_location() (+16 more)

### Community 50 - "get_active_adult_events"
Cohesion: 0.13
Nodes (19): _adult_event_visible_to_public(), find_active_events_on_day(), _find_month(), get_active_adult_events(), is_adult_event_past(), is_camp_stream_visible(), is_section_active(), _now_tbilisi() (+11 more)

### Community 51 - "sheets_service.py"
Cohesion: 0.06
Nodes (77): Credentials, now_tbilisi(), Current time as a TZ-aware Asia/Tbilisi datetime.      Single now-source for c, _env(), load_google_credentials(), _parse_service_account_json(), Railway-safe Google service-account credential loading.  A single resolver used, Read a variable straight from the process environment.      Reads ``os.environ`` (+69 more)

### Community 52 - "approved_copy_service.py"
Cohesion: 0.18
Nodes (18): ApprovedCopyError, ApprovedCopyFormatError, ApprovedCopyNotFound, _data(), get_approved_copy(), _load_yaml(), Any, Exception (+10 more)

### Community 53 - "_load_adult_events_raw"
Cohesion: 0.13
Nodes (18): activate_adult_event(), deactivate_adult_event(), delete_adult_event(), _load_adult_events_raw(), Generate a stable, file-safe id from a Georgian/Latin title.      Lowercases L, Return the raw `events` list from sections.yaml without     normalisation. Used, Write the `events` list back to the `adult_events` section.      Live QA Patch, Insert OR update an event under adult_events.events[] by id.      Returns vali (+10 more)

### Community 54 - "adult_llm_engine.py"
Cohesion: 0.15
Nodes (16): _adult_named_event_link(), _adult_named_event_price(), _build_context_message(), _has_adult_relative_cue(), _is_adult_self_reference(), _looks_like_child_age(), _maybe_capture_adult_target(), ADULT LLM engine — cultural-events flow tool-calling loop.  Mirrors the design (+8 more)

### Community 55 - "find_events_by_reference"
Cohesion: 0.13
Nodes (17): _event_query_tokens(), _event_search_haystack(), find_active_events_by_reference(), find_adult_event(), find_adult_events_matching(), find_events_by_reference(), Return a stem-form for a single Georgian / Latin word.      Lowercases (casefo, Stem-vs-stem comparison. A prefix match in either direction     counts so that (+9 more)

### Community 56 - "Parent sales policy — სიტყვის აკადემია"
Cohesion: 0.12
Nodes (15): 10. Adult interest rule, 11.1 Manager handoff preferred phrasing (CRITICAL — 2026-06-03), 11.2 No emojis in production replies (CRITICAL — 2026-06-03), 11. Tone, 12. Audience-aware tone adapters, 1. Role, 2. Conversation principle, 3. When user shows camp interest (+7 more)

### Community 57 - "template_loader.py"
Cohesion: 0.18
Nodes (15): AmbiguousTemplateKey, _get_group(), get_template(), _load_group(), KeyError, Path, RuntimeError, User-facing template loader.  Loads YAML templates from ``app/agent/templates/<g (+7 more)

### Community 58 - "Enum"
Cohesion: 0.17
Nodes (16): ContextSource, PendingWorkflowKind, PendingWorkflowSource, PendingWorkflowStatus, ProgramResolutionOutcome, ProgramResolutionReason, ProgramResolutionSource, Enum (+8 more)

### Community 59 - "adult_subscription_service.py"
Cohesion: 0.17
Nodes (15): _casefold(), is_already_subscribed(), is_negative_subscription_phrase(), is_subscription_consent_phrase(), is_unsubscribe_phrase(), Any, Adult Event Subscription Service (2026-06-08).  A standalone service that owns t, True when the user message looks like an explicit subscription     consent. Nega (+7 more)

### Community 60 - "sentry_service.py"
Cohesion: 0.15
Nodes (15): capture_exception(), capture_message(), init_sentry(), _is_active(), mask_sender(), Any, BaseException, Sentry / Error Monitoring — optional, safe-fallback wrapper.  This is the ONLY p (+7 more)

### Community 61 - "_build_sales_context"
Cohesion: 0.13
Nodes (15): _age_status(), _build_sales_context(), _last_bot_offered_booking(), Lean Prompt mode (Phase 4, Task 3). When ON, the engine loads the     ~120-160, Return True if the most-recent assistant message contained a     booking-offer, Return True when the user's current message is a confirmation of a     previous, Return True when the user's message contains a thanks phrase., Was a price-question asked by the user in the last few turns or     in the curr (+7 more)

### Community 62 - "conversation.py"
Cohesion: 0.07
Nodes (33): _bot_recently_in_adult_context(), _capture_child_age_from_contact(), _child_age_known(), _conversation_looks_resumed(), _extract_age_digits(), _in_camp_context(), _is_identity_question(), _is_pure_greeting_token() (+25 more)

### Community 63 - "_reasoning_reflect"
Cohesion: 0.17
Nodes (16): _display_date(), _extract_age(), _is_reschedule_scenario(), _mask_phone(), _parse_iso_datetime(), datetime, P3-C SAFE — backend tool executor for the PARENT LLM engine.  The executor is, Return a phone string safe for logs: first3 + *** + last3.      Empty input re (+8 more)

### Community 64 - "comment_service.py"
Cohesion: 0.21
Nodes (12): check_comment_followups(), detect_comment_intent(), _graph_base_url(), _has_active_conversation(), is_interest_intent(), _mark_comment_expired(), _openai_client(), OpenAI (+4 more)

### Community 65 - "determine_segment_from_post"
Cohesion: 0.18
Nodes (14): determine_segment_from_post(), extract_hashtags(), fetch_post_content(), _normalize_hashtag(), _post_content_fields(), Fetch a post's caption / message text via the Meta Graph API.      Uses platform, Map an admin_config section.type onto the legacy PARENT/ADULT/UNCLEAR     segmen, Admin-Panel-aware section resolver — primary routing path.      Reads the post c (+6 more)

### Community 66 - "_maybe_handle_subscription"
Cohesion: 0.17
Nodes (13): _deterministic_subscribe(), _has_pending_subscription_offer(), _is_direct_subscription_intent(), _is_subscription_consent(), _last_assistant_was_subscription_offer(), _maybe_handle_subscription(), Unicode letter-run tokeniser (Georgian + Latin). Used so short     affirmations, True when the agent has an outstanding subscription offer — either     the conv (+5 more)

### Community 67 - "_child_age_known"
Cohesion: 0.07
Nodes (29): _bot_recently_asked_child_age(), _capture_turn_facts(), _contains_age_range(), extract_distinct_child_ages(), _is_explicit_age_correction(), maybe_capture_child_age_fallback(), maybe_capture_phone_fallback(), _number_is_time_or_date() (+21 more)

### Community 68 - "_capture_turn_facts"
Cohesion: 0.11
Nodes (21): _bank_genitive(), _camp_installments_months(), _camp_price_answer(), _camp_price_banks(), _camp_price_block(), _camp_price_direct_answer(), _camp_price_full_block(), _camp_price_full_block_with_manager_deferral() (+13 more)

### Community 69 - "_parse_booking_datetime"
Cohesion: 0.15
Nodes (13): _attempt_router_booking(), _build_booking_ask_contact(), _build_booking_ask_phone_only(), _build_booking_ask_time(), _build_booking_safe_fallback(), _handle_booking_request(), _looks_like_price_question(), _missing_contact_fields() (+5 more)

### Community 70 - "build_section_dm"
Cohesion: 0.13
Nodes (19): _extract_relative_day_offset(), _extract_time(), Return the day offset for a Georgian relative-day phrase in     ``text`` (``-1``, Resolve a Georgian weekday phrase to a future date (Asia/Tbilisi),     or None w, Resolve a Georgian relative-date phrase (and optional time) in     ``text`` to a, Return ``(hour, minute)`` parsed from the first Georgian time     expression in, resolve_relative_datetime(), _resolve_weekday_date() (+11 more)

### Community 71 - "_conversation_has_assistant_turn"
Cohesion: 0.20
Nodes (10): _build_active_programs_welcome(), _first_turn_adult_events_intent(), _has_explicit_english_camp_intent(), _is_price_question(), _maybe_static_welcome(), Detect explicit price/cost question in user message (keyword-based, fast)., True when the message reads like an unambiguous English camp     enquiry: "Hell, True when the FIRST message clearly asks about ADULT cultural events —     an a (+2 more)

### Community 72 - "_maybe_handle_named_adult_event"
Cohesion: 0.18
Nodes (12): _has_genuine_event_name_token(), _has_specific_event_name(), _maybe_handle_named_adult_event(), True when at least one query token looks like a specific event NAME     (≥4 cha, Stricter than `_has_specific_event_name`: True only when a query token     look, A short list of the current active events (title + date), or a clear     „none, „This event has already taken place {date}" + the active list. NO     target/ag, „No event found by that name" + the active list + manager-verify. NO     target (+4 more)

### Community 73 - "detect_legacy_explicit_action"
Cohesion: 0.27
Nodes (11): _camp_context(), detect_legacy_explicit_action(), _has(), _has_link_form_marker(), _is_manager_contact_request(), _names_specific_event(), Legacy-mode explicit user-ACTION / topic detection (2026-06-25).  Intent/action-, Return the explicit action + topic for ``text`` (intent-level). Never     raises (+3 more)

### Community 74 - "send_dm_from_comment"
Cohesion: 0.18
Nodes (12): _build_active_adult_events_list_dm(), _build_adult_rich_dm(), _build_ambiguous_adult_event_dm(), _build_past_event_dm(), _is_sunday_school_section(), True when the resolved comment section is the Sunday-School program.      Detect, Send the first-contact DM in response to a public comment.      COMMENT FLOW PAT, Build an ADULT first-contact DM from admin-config active events only. (+4 more)

### Community 75 - "_load_conversation_from_redis"
Cohesion: 0.21
Nodes (12): Reconstruct a Conversation from a ``to_dict`` payload.          Symmetric with `, _conversation_redis_key(), _conversation_session_key(), _ensure_conversation_identity(), _get_or_create_conversation(), hydrate_from_redis(), _load_conversation_from_redis(), Follow-up Live-Test Hydrate Patch (2026-06-06).      Load every Redis-persiste (+4 more)

### Community 76 - "MessengerService"
Cohesion: 0.11
Nodes (17): BaseModel, ConversationResponse, IncomingMessage, _parse_iso_or_now(), Any, datetime, Best-effort ISO-string → datetime, falling back to ``utcnow``., Return a JSON-safe dict representation.          Datetimes become ISO strings. N (+9 more)

### Community 77 - "selected_state.py"
Cohesion: 0.22
Nodes (10): _build(), build_selected_state(), format_planner_policy(), format_selected_state(), _mask(), Selected-State Contract — Reasoning Layer Phase 3 Stage 2.1 (2026-06-24).  The l, Render the selected-state dict as a compact LLM system block., Render the planner decision as a compact LLM policy block (slim prompt). (+2 more)

### Community 78 - "sanitise_adult_response"
Cohesion: 0.20
Nodes (10): Sentence-level removal mirroring the sold-out strip. Only     called when the e, Strip sold-out claims that the LLM invented. Only called when     the executor, Bug 4: drop the filler „გმადლობთ." opener before age questions., Sentence-level removal of subscription success claims. Only     called when the, Apply the forbidden-phrase rewrite list to an outgoing ADULT reply.      Idemp, sanitise_adult_response(), _strip_false_subscription_success(), _strip_invented_price_missing_phrases() (+2 more)

### Community 79 - "clean_challenge_for_storage"
Cohesion: 0.24
Nodes (10): _challenge_clause_is_question(), clean_challenge_for_storage(), maybe_capture_challenge_fallback(), Split a raw challenge string into clauses on commas / semicolons and     the co, A clause is a factual question, but it may carry a leading goal     joined by „, Return only the meaningful camp goal(s) from a raw challenge     string — factu, Belt-and-braces structured capture of the parent's stated     concern / interes, _salvage_goal_before_question() (+2 more)

### Community 80 - "_suppress_redundant_age_question"
Cohesion: 0.15
Nodes (13): _next_missing_contact_prompt(), Ask only for the NEXT missing booking detail after the age is known:     phone, Anti-repeat guard: if the child's age is already known but the reply     still, A sentence that ASKS for the phone (an ask verb + „ნომერ"). A confirmation, Drop only the sentence(s) that re-ask for the phone; keep everything else., BUG-1 anti-repeat (2026-07-26 live test): the dynamic booking path confirmed a, _sentence_is_phone_ask(), _strip_phone_questions() (+5 more)

### Community 81 - "reserved_program_ids"
Cohesion: 0.25
Nodes (5): _is_camp_registration_open(), Effective admin product id for THIS consultation booking (Cap #2 / R1)., Registration-open check for the CONSULTATION booking flow, PER-PRODUCT., Program ids handled by curated deterministic flows (NOT the dynamic LLM     engi, reserved_program_ids()

### Community 82 - "PARENT communication style — სიტყვის აკადემია"
Cohesion: 0.20
Nodes (9): Behaviour by intent (one-line cheat sheet), Emoji, Forbidden behaviours, Forbidden phrases (robotic / menu-like), Language, Length and shape, PARENT communication style — სიტყვის აკადემია, Pivot phrases (when transitioning from discovery to a fact) (+1 more)

### Community 83 - "_events_matching_text"
Cohesion: 0.20
Nodes (10): _event_match_keys(), _events_matching_text(), _normalize_for_tag_match(), Normalize text for adult-event-tag substring comparison.      Lower-cases (case-, Substring match an event tag against a comment / caption.      Both sides are no, Return every operator-supplied string an event can be matched on.      The opera, Return every event with at least one match-key found in     ``text``. Order is p, Resolve the specific active adult event a comment is about.      Returns a 3-tup (+2 more)

### Community 84 - "learning_log_service.py"
Cohesion: 0.22
Nodes (9): log_turn(), _mask_pii(), Phase 5 — bounded, human-gated learning: PII-masked, capped, durable outcome-log, Mask phone-like digit runs in ``text``. Never raises; non-str input     is coerc, Append a masked ``record`` to the bounded learning log.      No-op when Redis is, Return the last ``n`` records (most-recent-last order preserved),     or ``[]``, Best-effort delete of the whole learning log. Never raises., recent() (+1 more)

### Community 85 - "skills_service.py"
Cohesion: 0.29
Nodes (9): load_skills(), _parse_skill_md(), Any, Skills registry (Phase 3, USE_SKILLS).  Reads operator/author-editable capabilit, Deterministically pick the most relevant ACTIVE skills for a turn.      Lowercas, Split a SKILL.md into (frontmatter dict, body).      Line-based (fixes critique, Return every ``app/agent/skills/*.md`` (except README.md) as a normalized     di, _safe_int() (+1 more)

### Community 86 - "_maybe_adult_offtopic_reply"
Cohesion: 0.22
Nodes (9): _gather_configured_adult_terms(), _has_standalone_here(), _is_notification_delivery_question(), _maybe_adult_offtopic_reply(), _maybe_handle_notification_delivery_question(), True when „აქ" (here) appears as a standalone token, not as a     substring of, Answer „where/how will the subscription notification arrive?"     directly (pla, Collect every casefold'ed term from admin_config that could     plausibly ident (+1 more)

### Community 87 - "maybe_handle_analyzer_interrupt"
Cohesion: 0.20
Nodes (10): _analyzer_enabled(), _build_clarifying_question(), _build_premium_price_answer(), maybe_handle_analyzer_interrupt(), Delegate camp price/payment rendering to the canonical parent flow.      `parent, Low-confidence fallback (LLM-analyzer branch). P2 polish.      Removed the awkwa, Indirection so tests can monkeypatch without touching frozen Settings., Top-level dispatcher.      Returns:       * a string — backend has decided to by (+2 more)

### Community 88 - "get_adult_events"
Cohesion: 0.25
Nodes (9): _build_fallback_event_from_section(), _coerce_int(), get_adult_events(), _normalize_adult_event(), Best-effort cast to int. Returns default on failure., Return a fully populated adult-event dict with every field the     LLM tool sur, Public wrapper around ``_normalize_adult_event``.      Use this from outside t, Live QA Patch (2026-06-05) — Bug 1A.      When the Admin Panel saves an adult (+1 more)

### Community 89 - "adult_event_broadcast_service.py"
Cohesion: 0.28
Nodes (8): broadcast_event(), build_broadcast_message(), _format_event_price(), Any, Adult Event Broadcast Service (2026-06-08).  Fan-out path that sends „ახალი ღონი, Fan out a new-event broadcast to consented subscribers.      Broadcast Safety Pa, Mirror of `comment_service._format_event_price` — kept inline     so this module, Render the full new-event broadcast message.      Includes only the operator-sav

### Community 90 - "find_approved_answer"
Cohesion: 0.33
Nodes (8): _count(), find_approved_answer(), load_answers(), Any, Operator-editable approved-answers store + deterministic matcher (Phase 5, Task, Return the `answers` list from approved_answers.yaml, read fresh on     every ca, Count triggers (lowercased) present as substrings of `low`. Mirrors     `camp_to, Return the highest-scoring approved answer `{id, answer}` for     `message`, or

### Community 91 - "detect_parent_interrupt_intent"
Cohesion: 0.32
Nodes (7): detect_parent_interrupt_intent(), _extract_entities(), _has_any_stem(), Any, Deterministic PARENT-turn intent detector.  A pure-Python, no-LLM, no-state clas, Return a best-effort entity bag — purely advisory.      Nothing here is treated, Deterministic intent classifier.      Walks the priority list and returns the *f

### Community 92 - ".is_whatsapp_configured"
Cohesion: 0.25
Nodes (4): normalize_whatsapp_number(), Manager WhatsApp recipient, normalised to digits-only         international for, True only when token + phone-number-id + a resolvable manager         recipient, Best-effort normalise a phone to digits-only international format for     the W

### Community 93 - "_build_active_events_list_block"
Cohesion: 0.25
Nodes (8): _build_active_events_list_block(), _build_specific_adult_event_dm(), _format_event_price(), Render an event's price as the user-facing string.      Mirrors the ADULT system, First-contact DM for a SPECIFIC adult event.      Lays out the operator-saved fi, Render a single event entry for the active-events catalogue DM.      Only operat, Render the active-events list as one multi-line string suitable     for substitu, _render_event_for_list()

### Community 94 - "_build_parent_rich_dm"
Cohesion: 0.29
Nodes (8): _build_camp_comment_dm(), _build_parent_rich_dm(), _is_camp_registration_open(), _locative_location(), Convert nominative Georgian location ("ამბასადორი კაჭრეთი") to     locative ("ამ, PATCH 3 — PARENT first-contact rich DM.      Resolution order:       1. Admin Pa, Return a comment-aware Summer-Camp first-contact DM.        * price question, _strip_camp_registration_cta()

### Community 95 - "kill_switch.py"
Cohesion: 0.29
Nodes (7): is_agent_enabled(), log_disabled_skip(), mask_sender(), Emergency Kill Switch — production-side disable.  When ``settings.AGENT_ENABLED`, True iff ``settings.AGENT_ENABLED`` is True.      Default-on: when the field is, Best-effort PII-light sender id for log lines.      Keeps the trailing 4 chars s, Single safe log line per skipped event.      No message contents, no secrets, no

### Community 96 - "_apply_safe_fields"
Cohesion: 0.22
Nodes (9): _add_pending_reminder(), _apply_safe_fields(), _approved_camp_copy(), _build_pending_booking_record(), _company(), Any, Append a short reminder to a factual answer (PART 5.C)., Apply analyzer-extracted ``provided_fields`` to the lead.      See PART 7: psych (+1 more)

### Community 97 - "canonical_session_key"
Cohesion: 0.43
Nodes (6): _legacy_conversation_redis_keys(), canonical_platform_key(), canonical_session_key(), _clean_part(), Canonical conversation/session key helpers.  The public transport platform can, Return ``platform:page_id:sender_id`` for conversation identity.

### Community 98 - "_build_system_prompt"
Cohesion: 0.27
Nodes (9): _msg_names_other_program(), True when the message NAMES an active NON-camp admin program (e.g. Disneyland,, _is_ambiguous(), match_dynamic_program(), Precise, flag-agnostic matcher: does a message NAME an active admin program?  Pu, True when a message token equals `term`, or (for terms >= 6 chars) `term`     is, Return {'program_id','type'} for the first ACTIVE section the message NAMES, _token_matches() (+1 more)

### Community 99 - "_ensure_adult_intro_followup"
Cohesion: 0.33
Nodes (6): _ends_with_dagexmarebit(), _ensure_adult_intro_followup(), _looks_like_bare_intro(), Heuristic: short ack response with an adult-event keyword and     no question., Live QA Bug Fix Patch (2026-06-04) — broader catch-all.      gpt-5.4-mini some, Append a next-step question if the response is a bare confirmation.      Looks

### Community 100 - "time"
Cohesion: 0.47
Nodes (5): OnReady, buffer_message(), _flush_after_delay(), Message debounce/batching layer.  Many users in messaging apps type in fragments, Append a message to the per-session buffer and restart debounce.      The callba

### Community 101 - "_build_slim_context"
Cohesion: 0.33
Nodes (4): _build_slim_context(), _planner_forbids_named_event_lookup(), True when the authoritative planner flagged the current turn as generic     adu, Build (selected_state, planner_policy) system blocks for slim mode from     the

### Community 102 - "_mark_subscription_offer_if_present"
Cohesion: 0.50
Nodes (4): _is_subscription_offer_question(), _mark_subscription_offer_if_present(), True when the outgoing/previous bot message is the future-event     notificatio, Record the pending-offer marker when the agent just asked the     future-event

### Community 103 - "load_google_credentials"
Cohesion: 0.22
Nodes (8): challenge_word_set(), dedupe_challenge_text(), _dedupe_repeated_block(), Collapse a verbatim repeated block: „X Y X Y" → „X Y", „X X" → „X".      Split, Case-folded word set of a challenge string (separators dropped).     Used to de, Deduplicate repeated concepts in a challenge string — clause-level     (on comm, _looks_like_adult_event_interest(), Return True when ``text`` looks like an ADULT event interest     description ra

### Community 104 - "parent_flow.py"
Cohesion: 0.04
Nodes (105): _active_configured_camp_streams(), _approved_camp_copy(), _book_fast_track_registration_url(), _camp_ended_direct(), _camp_future_information_not_announced_answer(), _camp_off_alt(), _camp_payment_process_answer(), _camp_public_policy_copy() (+97 more)

### Community 105 - "_planner_pre_answer"
Cohesion: 0.08
Nodes (30): _expire_past_booking_if_needed(), _final_camp_policy_has_current_parent_support(), _format_booked_datetime_short_georgian(), _has_positive_contact_request_marker(), _has_self_call_intent(), _is_explicit_manager_number_request(), _is_self_call_manager_request(), _lead_is_booked() (+22 more)

### Community 107 - "_send_email"
Cohesion: 0.32
Nodes (6): _is_manager_notified(), _manager_notified_redis_key(), _mark_manager_notified(), Write the duplicate-notification guard in both stores., Send a manager notification for a cancel/reschedule handoff.          Skips si, In-memory dict first; Redis fallback with legacy sender migration.

### Community 108 - "_build_sunday_school_comment_dm"
Cohesion: 0.50
Nodes (4): _build_ss_active_comment_dm(), _build_sunday_school_comment_dm(), Active Sunday-School comment DM built ONLY from populated operator fields     (n, Status-aware Sunday-School comment DM. NEVER returns Camp content.      coming_s

### Community 109 - "_has_adult_events_configured"
Cohesion: 0.50
Nodes (4): _has_adult_events_configured(), _parse_events_blocks(), Parse `settings.EVENTS` into a list of event dicts.      Only events with a non-, True when settings.EVENTS contains at least one real event block.      Stricter

### Community 110 - "_meta_error_summary"
Cohesion: 0.50
Nodes (4): _meta_error_summary(), Strip any `access_token=<value>` substring before it is logged., Return a privacy-safe one-line summary of a Meta Graph error body.      Surfaces, _redact_access_token()

### Community 111 - "_classify_segment"
Cohesion: 0.50
Nodes (4): _classify_segment(), _is_pure_greeting(), Return True only when message is a bare greeting (no other content).      "გამ, Deterministic keyword classifier — Phase 3.6A.      Returns one of: "PARENT",

### Community 116 - "lead_memory_service.py"
Cohesion: 0.31
Nodes (9): delete(), load(), maybe_seed_new_lead(), memory_key(), Durable per-lead memory (USE_LEAD_MEMORY). A compact, long-lived record of a lea, Fill ONLY empty Lead fields from memory (never overwrite a fact the     current, Called by `_ensure_lead` right after it creates a fresh Lead. Flag-gated     no-, save() (+1 more)

### Community 139 - "_record_pending_booking_for_slot"
Cohesion: 0.50
Nodes (4): _missing_booking_fields(), Order matters — match the legacy P1 helper used by the router., Persist an explicitly-chosen offered slot on     ``conversation.pending_booking, _record_pending_booking_for_slot()

### Community 140 - "_BusyCalendarQueryError"
Cohesion: 0.67
Nodes (3): _BusyCalendarQueryError, Exception, Raised by ``_free_busy_intervals`` when ANY configured busy     calendar query

### Community 141 - "get_active_sections"
Cohesion: 0.33
Nodes (6): get_active_child_program_names(), get_active_sections(), get_program_audience(), Return sections whose ``status`` is "active", whitespace/case-insensitive., Program audience — ``"child"`` | ``"adult"`` | ``"family"`` (2026-07-26)., Names of ACTIVE programs whose audience includes children (``child``/``family``)

### Community 142 - "to_tbilisi"
Cohesion: 0.50
Nodes (4): get_camp_status(), is_camp_active(), Return the operator-configured ``summer_camp.status``, normalised to     lower-, True when the camp is being sold (status ``active``); False for     ``hidden``

### Community 144 - "ExternalEmailDeliveryBlocked"
Cohesion: 0.67
Nodes (3): ExternalEmailDeliveryBlocked, BaseException, Raised by test-side guards when real SMTP delivery is attempted.      This inten

## Knowledge Gaps
- **39 isolated node(s):** `1. Role`, `2. Conversation principle`, `3.1 Age memory (CRITICAL invariant)`, `3.2 child_age leakage rule (CRITICAL)`, `3.3 Relative target rule` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Conversation` connect `Conversation` to `_handle_core`, `ParentToolExecutor`, `_ensure_lead`, `run_parent_llm_turn`, `conversation_service.py`, `_record_pending_booking_for_slot`, `Lead`, `FollowupService`, `adult_tool_executor.py`, `parent_reply_composer.py`, `adult_flow.py`, `_apply_client_emoji_policy`, `history`, `parent_turn_router.py`, `followup_service.py`, `FlowContext`, `_maybe_handle_camp_intro`, `_maybe_handle_event_inquiry`, `run_adult_llm_turn`, `_maybe_handle_availability_question`, `_response_for_intent`, `.get`, `adult_llm_engine.py`, `_build_sales_context`, `conversation.py`, `_maybe_handle_subscription`, `_child_age_known`, `_parse_booking_datetime`, `_conversation_has_assistant_turn`, `send_dm_from_comment`, `_load_conversation_from_redis`, `MessengerService`, `_suppress_redundant_age_question`, `_maybe_adult_offtopic_reply`, `maybe_handle_analyzer_interrupt`, `_mark_subscription_offer_if_present`, `parent_flow.py`, `_planner_pre_answer`?**
  _High betweenness centrality (0.227) - this node is a cross-community bridge._
- **Why does `Lead` connect `Lead` to `ParentToolExecutor`, `_ensure_lead`, `has_value`, `run_parent_llm_turn`, `parent_turn_analyzer.py`, `_record_pending_booking_for_slot`, `_BusyCalendarQueryError`, `FollowupService`, `adult_tool_executor.py`, `ExternalEmailDeliveryBlocked`, `parent_reply_composer.py`, `adult_flow.py`, `Conversation`, `parent_turn_router.py`, `followup_service.py`, `.from_dict`, `run_adult_llm_turn`, `_maybe_handle_availability_question`, `_response_for_intent`, `sheets_service.py`, `adult_llm_engine.py`, `_build_sales_context`, `conversation.py`, `_reasoning_reflect`, `_maybe_handle_subscription`, `_child_age_known`, `_parse_booking_datetime`, `MessengerService`, `clean_challenge_for_storage`, `_suppress_redundant_age_question`, `maybe_handle_analyzer_interrupt`, `_apply_safe_fields`, `_ensure_adult_intro_followup`, `_planner_pre_answer`, `lead_memory_service.py`?**
  _High betweenness centrality (0.217) - this node is a cross-community bridge._
- **Why does `ParentToolExecutor` connect `ParentToolExecutor` to `_ensure_lead`, `load_google_credentials`, `run_parent_llm_turn`, `_send_email`, `Lead`, `reserved_program_ids`, `Conversation`, `ProgramId`, `_reasoning_reflect`?**
  _High betweenness centrality (0.112) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `Conversation` (e.g. with `AdultToolExecutor` and `ParentToolExecutor`) actually correct?**
  _`Conversation` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `Lead` (e.g. with `AdultToolExecutor` and `ParentToolExecutor`) actually correct?**
  _`Lead` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `Settings` (e.g. with `_BusyCalendarQueryError` and `CalendarService`) actually correct?**
  _`Settings` has 8 INFERRED edges - model-reasoned connections that need verification._
- **What connects `1. Role`, `2. Conversation principle`, `3.1 Age memory (CRITICAL invariant)` to the rest of the system?**
  _39 weakly-connected nodes found - possible documentation gaps or missing edges._