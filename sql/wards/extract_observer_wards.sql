-- extract_observer_wards.sql
-- Returns ward placements from payload_json
-- columns: match_id, player_slot, ward_type, ward_time, x, y, z

SELECT
    m.match_id,
    json_extract(m.payload_json, '$.patch') AS patch,
    json_extract(p.value, '$.player_slot') AS player_slot,
    json_extract(o.value, '$.time') AS ward_time,
    json_extract(o.value, '$.x') AS x,
    json_extract(o.value, '$.y') AS y
FROM matches AS m
JOIN json_each(m.payload_json, '$.players') AS p
JOIN json_each(p.value, '$.obs_log') AS o
ORDER BY m.match_id, ward_time;