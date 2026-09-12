let ambiguousSequence = 0;

export function mockAmbiguous(kind: string): { id: string; url: string } {
  ambiguousSequence += 1;
  const result = {
    id: `mock-${kind}-${ambiguousSequence}`,
    url: `https://app.ambiguous.ai/mock/${kind}/${ambiguousSequence}`,
  };
  console.info("[hands] mock Ambiguous call", { kind, result });
  return result;
}

export function mockExa(query: string): {
  answer: string;
  citations: Array<{ title: string; url: string }>;
} {
  console.info("[hands] mock Exa answer", { query });
  return {
    answer: `Mock answer for: ${query}`,
    citations: [
      {
        title: "Mock source",
        url: "https://exa.ai/mock-source",
      },
    ],
  };
}
