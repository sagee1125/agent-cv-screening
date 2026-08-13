import { useEffect, useMemo, useState } from "react";
import { Button } from "../ui/button";
import type { SkillItem } from "../../types";
import { calculateRankOrderWeights } from "../../utils/weightCalculator";

interface SkillWeightDragProps {
  skills: SkillItem[];
  onChange?: (skills: SkillItem[]) => void;
}

export function SkillWeightDrag({ skills, onChange }: SkillWeightDragProps) {
  const [items, setItems] = useState<SkillItem[]>(skills);
  const [draggingId, setDraggingId] = useState<string | null>(null);

  useEffect(() => {
    setItems(skills);
  }, [skills]);

  const weightedItems = useMemo(() => {
    const ranked = calculateRankOrderWeights(items.map((skill) => ({ id: skill.id, name: skill.name })));
    return items.map((item) => ({
      ...item,
      weight: ranked.find((rankedItem) => rankedItem.id === item.id)?.weight ?? 0,
    }));
  }, [items]);

  const updateItems = (next: SkillItem[]) => {
    setItems(next);
    onChange?.(next);
  };

  const handleDragStart = (skillId: string) => {
    setDraggingId(skillId);
  };

  const handleDrop = (targetId: string) => {
    if (!draggingId || draggingId === targetId) {
      setDraggingId(null);
      return;
    }
    const sourceIndex = items.findIndex((item) => item.id === draggingId);
    const targetIndex = items.findIndex((item) => item.id === targetId);
    if (sourceIndex < 0 || targetIndex < 0) {
      setDraggingId(null);
      return;
    }
    const next = [...items];
    const [moving] = next.splice(sourceIndex, 1);
    next.splice(targetIndex, 0, moving);
    updateItems(next);
    setDraggingId(null);
  };

  const move = (index: number, offset: number) => {
    const target = index + offset;
    if (target < 0 || target >= items.length) return;
    const next = [...items];
    const [moving] = next.splice(index, 1);
    next.splice(target, 0, moving);
    updateItems(next);
  };

  return (
    <section className="space-y-3">
      <h3 className="text-base font-semibold text-slate-900">Skill Weight Drag</h3>
      <ul className="space-y-2">
        {weightedItems.map((skill, index) => (
          <li
            key={skill.id}
            draggable
            onDragStart={() => handleDragStart(skill.id)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => handleDrop(skill.id)}
            className="flex items-center justify-between rounded-md border border-slate-200 bg-white px-3 py-2 text-sm"
          >
            <div className="space-y-1">
              <p className="font-medium text-slate-800">{skill.name}</p>
              <p className="text-xs text-slate-500">Weight: {((skill.weight ?? 0) * 100).toFixed(1)}%</p>
            </div>
            <div className="flex items-center gap-1">
              <Button size="sm" variant="outline" onClick={() => move(index, -1)}>
                ↑
              </Button>
              <Button size="sm" variant="outline" onClick={() => move(index, 1)}>
                ↓
              </Button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
