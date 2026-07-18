<script>
  import { onMount, onDestroy } from 'svelte';
  import { subscribe } from '../events.js';

  // B1.6: spec_signed — signed_by + signed_at.
  let specs = $state([]); // {spec_id, signed_by, signed_at_millis}
  let connected = $state(false);
  let unsubscribe;

  function apply(msg) {
    const p = msg.payload;
    specs = [
      ...specs.filter((s) => s.spec_id !== p.spec_id),
      { spec_id: p.spec_id, signed_by: p.signer, signed_at_millis: p.signed_at_millis },
    ];
  }

  onMount(() => {
    unsubscribe = subscribe(['spec_signed'], apply, () => (connected = true));
  });
  onDestroy(() => unsubscribe?.());
</script>

<section>
  <h2>Signed specs</h2>
  <small>proj_signed_spec</small>
  {#if specs.length === 0}
    <p>no signed specs yet{connected ? '' : ' (connecting…)'}</p>
  {:else}
    <ul>
      {#each specs as s (s.spec_id)}
        <li><small>{s.spec_id}</small> — signed by {s.signed_by} at {s.signed_at_millis}</li>
      {/each}
    </ul>
  {/if}
</section>
