# Graph Report - app  (2026-07-26)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 2562 nodes · 5313 edges · 142 communities (135 shown, 7 thin omitted)
- Extraction: 94% EXTRACTED · 6% INFERRED · 0% AMBIGUOUS · INFERRED: 304 edges (avg confidence: 0.7)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `8794e421`
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
- to_tbilisi

## God Nodes (most connected - your core abstractions)
1. `Conversation` - 183 edges
2. `Lead` - 116 edges
3. `_handle_core()` - 61 edges
4. `Settings` - 51 edges
5. `run_parent_llm_turn()` - 33 edges
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

## Communities (142 total, 7 thin omitted)

### Community 0 - "_handle_core"
Cohesion: 0.04
Nodes (54): _camp_off_suppresses_info(), _dedupe_child_age_questions(), _ensure_adult_intro_followup_for_parent_flow(), _ensure_camp_age_question(), _format_multipoint_paragraphs(), _format_repaired_slot_response(), _handle_core(), _has_any_child_age_question() (+46 more)

### Community 1 - "load_knowledge"
Cohesion: 0.18
Nodes (12): KnowledgeNotFound, load_knowledge(), _path_for(), Any, FileNotFoundError, Path, Knowledge / business-fact loader.  Loads structured YAML knowledge files from ``, Raised when a named knowledge file is missing or malformed. (+4 more)

### Community 2 - "ParentToolExecutor"
Cohesion: 0.05
Nodes (57): challenge_word_set(), _contains_age_range(), dedupe_challenge_text(), _dedupe_repeated_block(), True when the message carries a numeric range („9-17", „9 დან 17",     „… 17 წლ, Collapse a verbatim repeated block: „X Y X Y" → „X Y", „X X" → „X".      Split, Case-folded word set of a challenge string (separators dropped).     Used to de, Deduplicate repeated concepts in a challenge string — clause-level     (on comm (+49 more)

### Community 3 - "_ensure_lead"
Cohesion: 0.04
Nodes (99): _bot_recently_asked_child_age(), maybe_capture_child_age_fallback(), Return ``message`` with any recognised Georgian phone number removed.      Liv, Belt-and-braces structured capture of the child's age when the     LLM acknowle, True when the most recent assistant turn asked for the child's     age — used t, _strip_phone_numbers(), _age_status_for_lead(), _booking_buffer_minutes() (+91 more)

### Community 4 - "camp_topic_facts.py"
Cohesion: 0.07
Nodes (59): answer_for_topic(), _canonical_overview_facts(), _count(), detect_camp_topic(), direct_call_fallback(), _eligibility_line(), _extract_any_age(), _extract_eligible_age() (+51 more)

### Community 5 - "timedelta"
Cohesion: 0.13
Nodes (23): apply_colloquial_time_to_iso(), extract_colloquial_hour(), _extract_half_hour(), _extract_relative_day_offset(), _extract_spelled_hour(), _extract_time(), _normalize_pm_hour(), now_tbilisi() (+15 more)

### Community 6 - "conversation_planner.py"
Cohesion: 0.06
Nodes (49): _booked(), _camp_subintent(), _context_was_closed(), _has_camp_concern(), _has_camp_signal(), _is_adult_age_self_statement(), _is_affirmation_like(), _is_greeting_only() (+41 more)

### Community 7 - "has_value"
Cohesion: 0.13
Nodes (8): has_value(), CalendarService, NotificationService, _twilio_configured(), log_sunday_school_lead(), _mask_sender_id(), Append ONE row to the SEPARATE ``SundaySchoolLeads`` tab.      Best-effort and i, SheetsService

### Community 8 - "run_parent_llm_turn"
Cohesion: 0.18
Nodes (19): _assistant_message_for_tool_calls(), _build_context_message(), _build_slim_context(), _choice_message(), _first_choice(), _message_content(), _parse_tool_args(), Any (+11 more)

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
Cohesion: 0.10
Nodes (42): Client, Lead, _adult_detail_lines(), _booking_text(), _build_adult_summary(), _build_email_subject(), _build_parent_summary(), _contact_info_lines() (+34 more)

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
Cohesion: 0.07
Nodes (35): _add_heart_after_first_sentence(), _add_heart_after_greeting(), _apply_client_emoji_policy(), apply_greeting_farewell_heart(), _bot_has_replied(), _build_active_programs_welcome(), _first_turn_adult_events_intent(), handle() (+27 more)

### Community 24 - "Conversation"
Cohesion: 0.04
Nodes (72): _apply_privacy_notice_policy(), _attempt_booking(), _book_selected_slot(), _booking_success_this_turn(), _compose_or_fallback(), _detect_safe_intent(), _end_with_consultation_offer(), _exact_detail_already_general() (+64 more)

### Community 26 - "models.py"
Cohesion: 0.13
Nodes (22): _program_mention_sort_key(), ProgramIdentityDefinition, ProgramPhraseRule, ProgramResolutionDecision, ProgramResolutionError, ProgramStemRule, ProgramTokenRule, Immutable domain types for the program registry. (+14 more)

### Community 27 - "ProgramId"
Cohesion: 0.13
Nodes (21): ProgramDefinition, ProgramId, ProgramOwnerReferences, Canonical program identifiers., An exact, already-canonical alias for one program., A symbolic reference to an existing owner, never a runtime object., Symbolic source owners associated with a program., Stable program identity and symbolic ownership metadata. (+13 more)

### Community 28 - "history"
Cohesion: 0.06
Nodes (36): _assistant_gave_camp_price(), _bot_in_manager_handoff_collection(), _bot_in_sunday_school_collection(), _bot_last_reply_asked_for_contact(), _bot_last_reply_asked_for_name(), _bot_recently_asked_challenge_question(), _bot_recently_gave_sports_answer(), _bot_recently_in_adult_context() (+28 more)

### Community 29 - "redis_state_service.py"
Cohesion: 0.12
Nodes (28): _conversation_ttl(), conversation_ttl_seconds(), delete(), _ensure_client(), exists(), get_json(), is_enabled(), log_startup_status() (+20 more)

### Community 30 - "calendar_service.py"
Cohesion: 0.14
Nodes (31): date, book_slot(), _booked_ranges(), _build_event_description(), _build_event_title(), _calendar_service(), cancel_calendar_event(), check_slot_available() (+23 more)

### Community 31 - "context_arbiter.py"
Cohesion: 0.15
Nodes (23): arbitrate_context(), _candidate_sort_key(), _consolidate_candidates(), _contains_phrase(), _decision(), _has_context_reset(), _is_fresh(), _is_structurally_elliptical() (+15 more)

### Community 32 - "parent_turn_router.py"
Cohesion: 0.13
Nodes (22): _build_cancel_response(), _build_identity_answer(), _build_manager_ask_phone(), _build_manager_handoff_with_phone(), _build_pending_ask_contact(), _build_pending_ask_name(), _build_pending_ask_phone(), _build_pending_invalid_phone() (+14 more)

### Community 33 - "Any"
Cohesion: 0.12
Nodes (27): find_section_by_hashtag(), find_section_from_comment_text(), find_section_from_post_hashtags(), find_section_from_post_id(), get_active_sections(), load_business_hours_mirror(), load_manager_contacts_mirror(), load_sections() (+19 more)

### Community 34 - "followup_service.py"
Cohesion: 0.11
Nodes (24): check_and_send_followups(), _effective_cadence(), _first_delay(), _followup_context(), _followup_message(), FollowupService, _maybe_send_followup_for_conversation(), _parse_last_bot_message_at() (+16 more)

### Community 35 - "parent_llm_engine.py"
Cohesion: 0.12
Nodes (20): _apply_dynamic_fact_normalisations(), _camp_age_bounds_safe(), _collapse_duplicated_tu(), _is_concern_preamble_sentence(), _is_explicit_age_correction(), _is_known_about_you_preamble(), _number_is_time_or_date(), P3-C SAFE — PARENT LLM engine (tool-calling loop).  The engine is the *reasoni (+12 more)

### Community 36 - ".from_dict"
Cohesion: 0.28
Nodes (5): _parse_iso_or_now(), Any, datetime, Reconstruct a Lead from a ``model_dump(mode="json")`` payload.          Symmetri, Best-effort ISO-string → datetime, falling back to ``utcnow``.

### Community 37 - "FlowContext"
Cohesion: 0.29
Nodes (3): _flow_context(), FlowContext, _segment_tone()

### Community 38 - "_maybe_handle_camp_intro"
Cohesion: 0.07
Nodes (32): _answer_camp_part(), _camp_price_question_count(), _camp_price_value(), _final_camp_policy_has_recent_camp_context(), _is_camp_price_intent(), _is_camp_registration_link_request(), _is_mixed_camp_adult_request(), _is_payment_question() (+24 more)

### Community 39 - "conversation_act.py"
Cohesion: 0.18
Nodes (21): _contains_any_phrase(), _contains_phrase(), _decision(), _has_stem(), _is_callback(), _is_correction(), _is_exact_phrase(), _is_greeting() (+13 more)

### Community 40 - "get_section"
Cohesion: 0.09
Nodes (23): get_camp_age_bounds(), get_camp_facts(), get_camp_registration_status(), get_camp_status(), get_program_age_bounds(), get_section(), get_sunday_school_status(), is_camp_active() (+15 more)

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
Cohesion: 0.09
Nodes (25): _final_camp_policy_has_registration_action(), _format_next_free_slots(), _free_slots_for_date_safe(), _is_explicit_consultation_request(), _join_georgian(), _looks_like_availability_question(), _maybe_handle_availability_question(), _next_days_free_slots() (+17 more)

### Community 47 - "_response_for_intent"
Cohesion: 0.13
Nodes (20): _build_no_concern_answer(), _build_out_of_scope_answer(), _build_premium_conditions_answer(), _build_premium_dates_answer(), _build_premium_location_answer(), _build_premium_registration_answer(), _camp(), _camp_registration_closed_answer() (+12 more)

### Community 48 - ".get"
Cohesion: 0.22
Nodes (7): Formatter, ContentRepository, _ConversationStore, Any, dict, In-memory store keyed by canonical session key.      Existing tests and a few, SafeFormatter

### Community 49 - "admin_config_service.py"
Cohesion: 0.16
Nodes (19): _backup(), _config_read_path(), delete_section(), _dump_yaml(), _ensure_admin_config_dir(), get_manager_phone(), load_templates(), _manager_phone_from_section() (+11 more)

### Community 50 - "get_active_adult_events"
Cohesion: 0.13
Nodes (20): _adult_event_month_stems(), _adult_event_visible_to_public(), find_active_events_on_day(), _find_month(), get_active_adult_events(), is_adult_event_past(), is_camp_stream_visible(), is_section_active() (+12 more)

### Community 51 - "sheets_service.py"
Cohesion: 0.08
Nodes (65): now_tbilisi(), Current time as a TZ-aware Asia/Tbilisi datetime.      Single now-source for c, _active_leads_headers(), append_lead(), _append_lead_row_aligned(), _bool_text(), _comment_row_to_dict(), _comment_to_row() (+57 more)

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
Cohesion: 0.15
Nodes (13): _age_status(), _build_sales_context(), _last_bot_offered_booking(), Return True if the most-recent assistant message contained a     booking-offer, Return True when the user's current message is a confirmation of a     previous, Return True when the user's message contains a thanks phrase., Was a price-question asked by the user in the last few turns or     in the curr, Return one of 'unknown', 'eligible', 'ineligible'. (+5 more)

### Community 62 - "conversation.py"
Cohesion: 0.20
Nodes (9): BaseModel, ConversationResponse, IncomingMessage, _parse_iso_or_now(), Any, datetime, Best-effort ISO-string → datetime, falling back to ``utcnow``., Return a JSON-safe dict representation.          Datetimes become ISO strings. N (+1 more)

### Community 63 - "_reasoning_reflect"
Cohesion: 0.40
Nodes (5): True when the user's OWN message this turn carries a phone-like run —     the a, Verify ``answer``'s facts against ``grounded`` (per-class). Returns     ``(fina, _reasoning_digits(), _reasoning_message_has_phone(), _reasoning_reflect()

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
Cohesion: 0.08
Nodes (27): extract_distinct_child_ages(), Return the distinct plausible child ages (5–20) a parent stated in a     COMPAC, _build_multi_child_ack(), _capture_child_age_from_contact(), _child_age_known(), _conversation_looks_resumed(), _is_pure_greeting_token(), _is_reschedule_request() (+19 more)

### Community 68 - "_capture_turn_facts"
Cohesion: 0.50
Nodes (4): _capture_turn_facts(), maybe_capture_phone_fallback(), Pre-turn deterministic capture of the facts the parent gave THIS turn     (chil, Belt-and-braces capture of the parent's phone — the phone counterpart     of :f

### Community 69 - "_parse_booking_datetime"
Cohesion: 0.13
Nodes (15): _attempt_router_booking(), _build_booking_ask_contact(), _build_booking_ask_phone_only(), _build_booking_ask_time(), _build_booking_safe_fallback(), _handle_booking_request(), _looks_like_price_question(), _missing_contact_fields() (+7 more)

### Community 70 - "build_section_dm"
Cohesion: 0.15
Nodes (12): build_section_dm(), get_template(), get_visible_camp_streams(), _locative_location(), dict, Filter camp streams down to the ones still shown to users.      A stream survi, A dict that returns "" for missing keys when used with format_map.      Keeps, Render a template with a forgiving placeholder substitution.      Returns an e (+4 more)

### Community 71 - "_conversation_has_assistant_turn"
Cohesion: 0.50
Nodes (4): _conversation_has_assistant_turn(), True when the bot has already produced at least one reply in history., Remove a sentence-initial greeting once the conversation is underway.      A g, _strip_mid_conversation_greeting()

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
Cohesion: 0.22
Nodes (8): get_user_profile(), _graph_base_url(), _mask_access_token(), MessengerService, Replace any `access_token=<value>` with a masked marker. Used on     error strin, COMMENT FLOW PATCH 2 — private reply to a Facebook / Instagram     public commen, send_message(), send_private_reply()

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
Cohesion: 0.22
Nodes (9): _next_missing_contact_prompt(), Ask only for the NEXT missing booking detail after the age is known:     phone, Anti-repeat guard: if the child's age is already known but the reply     still, _suppress_redundant_age_question(), contains_child_age_question(), Shared child-age-QUESTION matcher (Phase 1 fix, 2026-06-24).  ONE regex used by, True when ``text`` contains a child-age QUESTION in any of the real     Georgian, Remove only the sentence(s) that ask the child's age, keeping the rest     of th (+1 more)

### Community 81 - "reserved_program_ids"
Cohesion: 0.12
Nodes (16): build_active_tools(), _dynamic_programs_prompt_suffix(), Return {fact_class: trusted_value} for ONLY the classes in     ``needed_facts``, Compact Georgian "label: value" block of the grounded facts for the     ANSWER, True when the message NAMES an active NON-reserved (dynamic) program —     such, Assemble the extra ANSWER system directive from the plan + grounded     facts +, Flag-gated ANALYZE + GROUND. Returns (grounded_facts, plan_directive).     Flag, Flag-off ⇒ exactly PARENT_TOOLS (byte-identical). Flag-on ⇒ + generic     progr (+8 more)

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
Nodes (9): _build_fallback_event_from_section(), _coerce_int(), get_adult_events(), _normalize_adult_event(), Public wrapper around ``_normalize_adult_event``.      Use this from outside t, Live QA Patch (2026-06-05) — Bug 1A.      When the Admin Panel saves an adult, Return the normalised list of adult events from admin_config.      Reads ``adu, Best-effort cast to int. Returns default on failure. (+1 more)

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
Cohesion: 0.25
Nodes (8): _add_pending_reminder(), _apply_safe_fields(), _approved_camp_copy(), _build_pending_booking_record(), Any, Append a short reminder to a factual answer (PART 5.C)., Apply analyzer-extracted ``provided_fields`` to the lead.      See PART 7: psych, Construct the JSON-safe ``pending_booking`` dict.      Spec PART 1/2: everything

### Community 97 - "canonical_session_key"
Cohesion: 0.43
Nodes (6): _legacy_conversation_redis_keys(), canonical_platform_key(), canonical_session_key(), _clean_part(), Canonical conversation/session key helpers.  The public transport platform can, Return ``platform:page_id:sender_id`` for conversation identity.

### Community 98 - "_build_system_prompt"
Cohesion: 0.15
Nodes (13): _apply_offtopic_intelligence(), _approved_answer_prompt_suffix(), _build_system_prompt(), Tell the LLM to check for an operator-approved answer on an unclear     questio, Tell the LLM the program-topic facts tool exists. Empty string when the     fla, Inject the situational SKILL.md capability pack(s) selected for this turn., Slim Prompt mode (Class 4). When ON, the engine loads the short     `parent_cor, Lean Prompt mode (Phase 4, Task 3). When ON, the engine loads the     ~120-160 (+5 more)

### Community 99 - "_ensure_adult_intro_followup"
Cohesion: 0.33
Nodes (6): _ends_with_dagexmarebit(), _ensure_adult_intro_followup(), _looks_like_bare_intro(), Heuristic: short ack response with an adult-event keyword and     no question., Live QA Bug Fix Patch (2026-06-04) — broader catch-all.      gpt-5.4-mini some, Append a next-step question if the response is a bare confirmation.      Looks

### Community 100 - "time"
Cohesion: 0.28
Nodes (8): _parse_custom_datetime(), OnReady, _parse_hm(), buffer_message(), _flush_after_delay(), Message debounce/batching layer.  Many users in messaging apps type in fragments, Append a message to the per-session buffer and restart debounce.      The callba, time

### Community 101 - "_build_slim_context"
Cohesion: 0.33
Nodes (4): _build_slim_context(), _planner_forbids_named_event_lookup(), True when the authoritative planner flagged the current turn as generic     adu, Build (selected_state, planner_policy) system blocks for slim mode from     the

### Community 102 - "_mark_subscription_offer_if_present"
Cohesion: 0.50
Nodes (4): _is_subscription_offer_question(), _mark_subscription_offer_if_present(), True when the outgoing/previous bot message is the future-event     notificatio, Record the pending-offer marker when the agent just asked the     future-event

### Community 103 - "load_google_credentials"
Cohesion: 0.28
Nodes (8): Credentials, _env(), load_google_credentials(), _parse_service_account_json(), Railway-safe Google service-account credential loading.  A single resolver used, Read a variable straight from the process environment.      Reads ``os.environ``, ``json.loads`` the service-account JSON and repair escaped newlines.      A very, Resolve Google service-account credentials for ``scopes``.      See the module d

### Community 104 - "parent_flow.py"
Cohesion: 0.03
Nodes (115): _active_configured_camp_streams(), _approved_camp_copy(), _bank_genitive(), _book_fast_track_registration_url(), _bot_last_gave_payment_method_answer(), _camp_future_information_not_announced_answer(), _camp_installments_months(), _camp_payment_process_answer() (+107 more)

### Community 105 - "_planner_pre_answer"
Cohesion: 0.08
Nodes (27): _expire_past_booking_if_needed(), _format_booked_datetime_short_georgian(), _lead_is_booked(), _manager_contact_for_fallback(), _manager_number_answer_fallback(), planner_final_validate(), _planner_pre_answer(), _planner_protect_manager_phone() (+19 more)

### Community 107 - "_send_email"
Cohesion: 0.15
Nodes (13): EmailMessage, _mask_recipient(), notify_manager_handoff(), notify_sunday_school_handoff(), EMAIL-ONLY manager handoff for a Sunday-School lead (planned July).      Sunday, Message-only operator handoff notification — NO Sheets / Calendar.      Used for, Production SMTP transport. Tests replace ``_email_transport``., Send the manager notification email.      Gates (return False without raising): (+5 more)

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

### Community 142 - "to_tbilisi"
Cohesion: 0.50
Nodes (4): format_tbilisi_datetime(), Return a TZ-aware datetime in Asia/Tbilisi.      Convention: a *naive* input is, Format a datetime as an Asia/Tbilisi ISO-8601 string.      Returns ``""`` for ``, to_tbilisi()

## Knowledge Gaps
- **39 isolated node(s):** `1. Role`, `2. Conversation principle`, `3.1 Age memory (CRITICAL invariant)`, `3.2 child_age leakage rule (CRITICAL)`, `3.3 Relative target rule` (+34 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Conversation` connect `Conversation` to `_handle_core`, `ParentToolExecutor`, `_ensure_lead`, `run_parent_llm_turn`, `conversation_service.py`, `_record_pending_booking_for_slot`, `Lead`, `adult_tool_executor.py`, `parent_reply_composer.py`, `adult_flow.py`, `_apply_client_emoji_policy`, `history`, `parent_turn_router.py`, `followup_service.py`, `FlowContext`, `_maybe_handle_camp_intro`, `_maybe_handle_event_inquiry`, `run_adult_llm_turn`, `_maybe_handle_availability_question`, `_response_for_intent`, `.get`, `adult_llm_engine.py`, `_build_sales_context`, `conversation.py`, `_maybe_handle_subscription`, `_child_age_known`, `_capture_turn_facts`, `_parse_booking_datetime`, `_conversation_has_assistant_turn`, `send_dm_from_comment`, `_load_conversation_from_redis`, `_suppress_redundant_age_question`, `reserved_program_ids`, `_maybe_adult_offtopic_reply`, `maybe_handle_analyzer_interrupt`, `_mark_subscription_offer_if_present`, `parent_flow.py`, `_planner_pre_answer`?**
  _High betweenness centrality (0.230) - this node is a cross-community bridge._
- **Why does `Lead` connect `Lead` to `ParentToolExecutor`, `_ensure_lead`, `has_value`, `run_parent_llm_turn`, `parent_turn_analyzer.py`, `_record_pending_booking_for_slot`, `_BusyCalendarQueryError`, `adult_tool_executor.py`, `parent_reply_composer.py`, `adult_flow.py`, `Conversation`, `calendar_service.py`, `parent_turn_router.py`, `followup_service.py`, `.from_dict`, `run_adult_llm_turn`, `_response_for_intent`, `sheets_service.py`, `adult_llm_engine.py`, `_build_sales_context`, `conversation.py`, `_maybe_handle_subscription`, `_child_age_known`, `_capture_turn_facts`, `_parse_booking_datetime`, `clean_challenge_for_storage`, `_suppress_redundant_age_question`, `reserved_program_ids`, `maybe_handle_analyzer_interrupt`, `_apply_safe_fields`, `_ensure_adult_intro_followup`, `_planner_pre_answer`, `_send_email`, `lead_memory_service.py`?**
  _High betweenness centrality (0.224) - this node is a cross-community bridge._
- **Why does `ParentToolExecutor` connect `ParentToolExecutor` to `_handle_core`, `_ensure_lead`, `run_parent_llm_turn`, `Lead`, `Conversation`, `ProgramId`?**
  _High betweenness centrality (0.122) - this node is a cross-community bridge._
- **Are the 9 inferred relationships involving `Conversation` (e.g. with `AdultToolExecutor` and `ParentToolExecutor`) actually correct?**
  _`Conversation` has 9 INFERRED edges - model-reasoned connections that need verification._
- **Are the 11 inferred relationships involving `Lead` (e.g. with `AdultToolExecutor` and `ParentToolExecutor`) actually correct?**
  _`Lead` has 11 INFERRED edges - model-reasoned connections that need verification._
- **Are the 8 inferred relationships involving `Settings` (e.g. with `_BusyCalendarQueryError` and `CalendarService`) actually correct?**
  _`Settings` has 8 INFERRED edges - model-reasoned connections that need verification._
- **What connects `1. Role`, `2. Conversation principle`, `3.1 Age memory (CRITICAL invariant)` to the rest of the system?**
  _39 weakly-connected nodes found - possible documentation gaps or missing edges._