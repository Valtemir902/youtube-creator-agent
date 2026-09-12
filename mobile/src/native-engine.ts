export type ChannelSnapshot = {
  schema_version: 1;
  captured_at: string;
  channel_id: string;
  subscribers?: number;
  total_views?: number;
  video_count?: number;
  search_share?: number;
  shorts_share_of_recent_views?: number;
  long_share_of_recent_views?: number;
  titles?: string[];
  descriptions?: string[];
  tags?: string[];
};

export type NativeAnalysis = {
  schema_version: 1;
  computed_at: string;
  scores: Record<string, number>;
  warnings: string[];
  opportunities: string[];
};

export function analyzeSnapshot(s: ChannelSnapshot): NativeAnalysis {
  const warnings: string[] = [];
  const opportunities: string[] = [];
  const scores: Record<string, number> = {};
  const titles = s.titles ?? [];
  const descriptions = s.descriptions ?? [];

  const titleLengths = titles.map(x => x.trim().length).filter(Boolean);
  scores.title_structure = titleLengths.length
    ? Math.round(100 * titleLengths.filter(n => n >= 35 && n <= 70).length / titleLengths.length)
    : 0;

  const descLengths = descriptions.map(x => x.trim().length).filter(Boolean);
  scores.description_coverage = descLengths.length
    ? Math.round(100 * descLengths.filter(n => n >= 120).length / descLengths.length)
    : 0;

  const shorts = Number(s.shorts_share_of_recent_views ?? 0);
  const longs = Number(s.long_share_of_recent_views ?? 0);
  scores.format_balance = Math.round(Math.max(0, 100 - Math.abs(shorts - longs) * 100));

  if (scores.title_structure < 60) warnings.push('Muitos títulos estão fora da faixa estrutural recomendada.');
  if (scores.description_coverage < 60) warnings.push('Há descrições curtas ou incompletas no inventário analisado.');
  if ((s.search_share ?? 0) < 0.1) opportunities.push('Baixa participação de busca no período pode justificar revisão de intenção e palavras-chave.');

  return {
    schema_version: 1,
    computed_at: new Date().toISOString(),
    scores,
    warnings,
    opportunities
  };
}
