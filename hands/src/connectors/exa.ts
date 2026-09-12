import { Exa } from "exa-js";

import { mockExa } from "../mock.js";

export type ExaAnswer = {
  answer: string;
  citations: Array<{ title: string; url: string }>;
};

let client: Exa | undefined;

export async function answer(query: string): Promise<ExaAnswer> {
  const apiKey = process.env.EXA_API_KEY?.trim();
  if (!apiKey) {
    return mockExa(query);
  }

  client ??= new Exa(apiKey);
  const response = await client.answer(query, { text: true });
  return {
    answer:
      typeof response.answer === "string"
        ? response.answer
        : JSON.stringify(response.answer, null, 2),
    citations: response.citations
      .filter((citation) => Boolean(citation.url))
      .map((citation) => ({
        title: citation.title || citation.url,
        url: citation.url,
      })),
  };
}
