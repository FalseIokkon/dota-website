-- extract_observer_wards.sql
-- Returns ward placements from payload_json
-- columns: match_id, player_slot, ward_type, ward_time, x, y, z

SELECT
    m.rowid AS match_row,
    json_extract(m.payload_json, '$.match_id') AS match_id,
    json_extract(p.value, '$.player_slot') AS player_slot,
    json_extract(o.value, '$.time') AS ward_time,
    json_extract(o.value, '$.x') AS x,
    json_extract(o.value, '$.y') AS y,
    json_extract(o.value, '$.z') AS z
FROM matches AS m
JOIN json_each(m.payload_json, '$.players') AS p
JOIN json_each(p.value, '$.obs_log') AS o
ORDER BY match_id, ward_time;