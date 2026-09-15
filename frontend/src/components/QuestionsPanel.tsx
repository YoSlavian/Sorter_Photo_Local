import { useState } from 'react';
import { useStudio } from '../state/store';

/**
 * The clarification panel.
 *
 * When a description is under-specified the engine asks instead of guessing;
 * this is where those questions are answered. Answers change the model, never
 * the text, so the authored description stays the record of what was written.
 */
export function QuestionsPanel() {
  const diagram = useStudio((state) => state.diagram);
  const answer = useStudio((state) => state.answer);
  const select = useStudio((state) => state.select);
  const busy = useStudio((state) => state.busy);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  const questions = diagram?.clarifications ?? [];
  if (!questions.length) {
    return (
      <p className="ba-panel__empty">
        Уточнений нет — описание было понято однозначно.
      </p>
    );
  }

  const filled = Object.values(answers).filter((value) => value.trim()).length;

  return (
    <>
      <div className="ba-summary">
        <span className="ba-pill ba-pill--warning">Требуется уточнение: {questions.length}</span>
      </div>

      <div style={{ padding: 10 }}>
        {questions.map((question) => {
          const current = answers[question.id] ?? '';
          const freeText = question.options.find((option) => option.freeText);
          const choices = question.options.filter((option) => !option.freeText);
          return (
            <div className="ba-question" key={question.id}>
              <div className="ba-question__text">{question.question}</div>
              {question.sentence && (
                <button
                  type="button"
                  className="ba-question__source"
                  style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer' }}
                  onClick={() => question.elementId && select(question.elementId)}
                >
                  «{question.sentence}»
                </button>
              )}

              <div className="ba-question__options">
                {choices.map((option) => (
                  <button
                    type="button"
                    key={option.value}
                    className="ba-chip"
                    aria-pressed={current === option.value}
                    onClick={() =>
                      setAnswers((previous) => ({
                        ...previous,
                        [question.id]: current === option.value ? '' : option.value,
                      }))
                    }
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              {(freeText || !choices.length) && (
                <input
                  className="ba-field__control"
                  style={{ marginTop: 7 }}
                  placeholder={choices.length ? 'Свой вариант…' : 'Ваш ответ…'}
                  value={choices.some((option) => option.value === current) ? '' : current}
                  onChange={(event) =>
                    setAnswers((previous) => ({ ...previous, [question.id]: event.target.value }))
                  }
                />
              )}
            </div>
          );
        })}

        <button
          type="button"
          className="ba-btn ba-btn--primary"
          disabled={busy || filled === 0}
          onClick={() => {
            const payload = Object.fromEntries(
              Object.entries(answers).filter(([, value]) => value.trim()),
            );
            void answer(payload).then(() => setAnswers({}));
          }}
        >
          Применить ответы ({filled})
        </button>
      </div>
    </>
  );
}
