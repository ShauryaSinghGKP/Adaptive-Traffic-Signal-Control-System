-- Upgrade databases created by the original two-axis version without deleting run history.
ALTER TABLE scheduling_decisions
    ADD COLUMN selected_approach ENUM('north','east','south','west') NULL;

-- Legacy decisions selected a two-direction axis, not one approach; keep those
-- values in selected_axis and leave the new single-approach field empty.
UPDATE scheduling_decisions
SET selected_approach = NULL
WHERE selected_axis IS NOT NULL;
