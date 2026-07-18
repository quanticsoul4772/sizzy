<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B1.6: research interview — question_asked / question_answered.
  let questions = $state([]); // {question_id, question_text, answered, answer_text}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    if (msg.event_type === 'question_asked') {
      questions = [
        ...questions.filter((q) => q.question_id !== p.question_id),
        { question_id: p.question_id, question_text: p.question_text, answered: false, answer_text: '' },
      ];
    } else if (msg.event_type === 'question_answered') {
      questions = questions.map((q) =>
        q.question_id === p.question_id ? { ...q, answered: true, answer_text: p.answer_text } : q,
      );
    }
  }

  onMount(() => {
    unsubscribe = subscribe(['question_asked', 'question_answered'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Research questions</h2>
  <small>proj_questions</small>
  {#if questions.length === 0}
    <p>no research questions yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each questions as q (q.question_id)}
        <li>
          <span>{q.answered ? '[answered]' : '[unanswered]'}</span>
          {q.question_text}{q.answered ? ` → ${q.answer_text}` : ''}
        </li>
      {/each}
    </ul>
  {/if}
</section>
