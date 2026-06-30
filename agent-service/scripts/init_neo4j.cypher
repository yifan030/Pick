// init_neo4j.cypher — Run once after Neo4j first starts

// ── Constraints ────────────────────────────────────────────
CREATE CONSTRAINT user_id_unique IF NOT EXISTS
FOR (u:User) REQUIRE u.user_id IS UNIQUE;

CREATE CONSTRAINT shop_id_unique IF NOT EXISTS
FOR (s:Shop) REQUIRE s.shop_id IS UNIQUE;

CREATE CONSTRAINT area_name_unique IF NOT EXISTS
FOR (a:Area) REQUIRE a.name IS UNIQUE;

CREATE CONSTRAINT category_id_unique IF NOT EXISTS
FOR (c:Category) REQUIRE c.category_id IS UNIQUE;

CREATE CONSTRAINT voucher_id_unique IF NOT EXISTS
FOR (v:Voucher) REQUIRE v.voucher_id IS UNIQUE;

CREATE CONSTRAINT eventref_id_unique IF NOT EXISTS
FOR (e:EventRef) REQUIRE e.event_id IS UNIQUE;

CREATE CONSTRAINT sessionref_id_unique IF NOT EXISTS
FOR (s:SessionRef) REQUIRE s.session_id IS UNIQUE;

CREATE CONSTRAINT agentcaseref_id_unique IF NOT EXISTS
FOR (ac:AgentCaseRef) REQUIRE ac.case_id IS UNIQUE;

// Profile atom uniqueness (user_id + property combination)
CREATE CONSTRAINT taste_pref_unique IF NOT EXISTS
FOR (tp:TastePreference) REQUIRE (tp.user_id, tp.property) IS UNIQUE;

CREATE CONSTRAINT dietary_pref_unique IF NOT EXISTS
FOR (dp:DietaryPreference) REQUIRE (dp.user_id, dp.constraint) IS UNIQUE;

CREATE CONSTRAINT cuisine_pref_unique IF NOT EXISTS
FOR (cp:CuisinePreference) REQUIRE (cp.user_id, cp.cuisine) IS UNIQUE;

CREATE CONSTRAINT area_pref_unique IF NOT EXISTS
FOR (ap:AreaPreference) REQUIRE (ap.user_id, ap.area) IS UNIQUE;

CREATE CONSTRAINT scene_pref_unique IF NOT EXISTS
FOR (sp:ScenePreference) REQUIRE (sp.user_id, sp.scene) IS UNIQUE;

CREATE CONSTRAINT budget_pref_unique IF NOT EXISTS
FOR (bp:BudgetPreference) REQUIRE (bp.user_id, bp.type) IS UNIQUE;

CREATE CONSTRAINT constraint_pref_unique IF NOT EXISTS
FOR (cp2:ConstraintPreference) REQUIRE (cp2.user_id, cp2.constraint) IS UNIQUE;

// ── Indexes ────────────────────────────────────────────────
CREATE INDEX shop_area_idx IF NOT EXISTS FOR (s:Shop) ON (s.area);
CREATE INDEX shop_type_idx IF NOT EXISTS FOR (s:Shop) ON (s.type);
CREATE INDEX taste_confidence_idx IF NOT EXISTS FOR (tp:TastePreference) ON (tp.confidence);
CREATE INDEX cuisine_confidence_idx IF NOT EXISTS FOR (cp:CuisinePreference) ON (cp.confidence);
CREATE INDEX area_pref_confidence_idx IF NOT EXISTS FOR (ap:AreaPreference) ON (ap.confidence);
CREATE INDEX eventref_user_idx IF NOT EXISTS FOR (e:EventRef) ON (e.user_id);
CREATE INDEX sessionref_user_idx IF NOT EXISTS FOR (s:SessionRef) ON (s.user_id);
