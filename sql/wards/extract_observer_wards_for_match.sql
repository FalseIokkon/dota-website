-- extract_observer_ward_single.sql
-- Returns ward placements from payload_json, ONLY for ONE match
-- columns: match_id, player_slot, ward_type, ward_time, x, y, z

SELECT
    json_extract(m.payload_json, '$.match_id') AS match_id,
    json_extract(p.value, '$.player_slot') AS player_slot,
    'observer' AS ward_type,
    json_extract(w.value, '$.time') AS ward_time,
    json_extract(w.value, '$.x') AS x,
    json_extract(w.value, '$.y') AS y
FROM matches AS m
JOIN json_each(m.payload_json, '$.players') AS p
JOIN json_each(p.value, '$.obs_log') AS w
WHERE json_extract(m.payload_json, '$.match_id') = 8646479938;