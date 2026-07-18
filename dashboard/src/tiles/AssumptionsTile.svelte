<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B1.6: assumption_flagged — confidence + low-confidence indicator.
  let assumptions = $state([]); // {text, confidence, low}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    assumptions = [...assumptions, { text: p.text, confidence: p.confidence, low: !!p.low_confidence_flag }].slice(-50);
  }

  onMount(() => {
    unsubscribe = subscribe(['assumption_flagged'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Assumptions</h2>
  <small>proj_assumptions</small>
  {#if assumptions.length === 0}
    <p>no assumptions yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each assumptions as a, i (i)}
        <li>
          <span>conf {a.confidence}</span>
          {#if a.low}<span> [low confidence]</span>{/if}
          — {a.text}
        </li>
      {/each}
    </ul>
  {/if}
</section>
