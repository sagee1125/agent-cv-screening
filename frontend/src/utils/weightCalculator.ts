export interface RankedSkill {
  id: string;
  name: string;
}

export interface WeightedSkill extends RankedSkill {
  weight: number;
}

export function calculateRankOrderWeights(skills: RankedSkill[]): WeightedSkill[] {
  if (skills.length === 0) {
    return [];
  }

  const denominator = (skills.length * (skills.length + 1)) / 2;
  return skills.map((skill, index) => {
    const rank = skills.length - index;
    const weight = Number((rank / denominator).toFixed(4));
    return { ...skill, weight };
  });
}
