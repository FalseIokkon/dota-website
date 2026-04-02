-- extract_sentry_wards.sql
-- Returns ward placements from payload_json
-- columns: match_id, player_slot, ward_type, ward_time, x, y, z

SELECT
    m.match_id AS match_id,
    json_extract(m.payload_json, '$.patch') AS patch,
    json_extract(p.value, '$.player_slot') AS player_slot,
    'sentry' AS ward_type,
    json_extract(s.value, '$.time') AS ward_time,
    json_extract(s.value, '$.x') AS x,
    json_extract(s.value, '$.y') AS y,
    json_extract(s.value, '$.z') AS z
FROM matches AS m
JOIN json_each(m.payload_json, '$.players') AS p
JOIN json_each(p.value, '$.sen_log') AS s
ORDER BY m.match_id, ward_time;