import * as anchor from "@coral-xyz/anchor";
import { Program } from "@coral-xyz/anchor";
import { ChainCustody } from "../target/types/chain_custody";
import { Keypair, SystemProgram, PublicKey } from "@solana/web3.js";
import { assert } from "chai";

describe("chain-custody", () => {
  // Configure the client to use the local cluster.
  const provider = anchor.AnchorProvider.env();
  anchor.setProvider(provider);
  const program = anchor.workspace.ChainCustody as Program<ChainCustody>;

  it("Is initialized!", async () => {
    const materialKeypair = Keypair.generate();

    // 1) Initialize material
    await program.methods
      .initializeMaterial("MatA123")
      .accounts({
        materialAccount: materialKeypair.publicKey,
        initializer:      provider.wallet.publicKey,
        systemProgram:    SystemProgram.programId,
      })
      .signers([materialKeypair])
      .rpc();

    // 2) Fetch and assert
    const account = await program.account.material.fetch(materialKeypair.publicKey);
    assert.ok(account.currentHolder.equals(provider.wallet.publicKey));
    assert.equal(account.lastSequence.toNumber(), 0);
  });

  it("Transfers custody", async () => {
    const materialKeypair = Keypair.generate();

    // 1) Initialize a new material
    await program.methods
      .initializeMaterial("MatB456")
      .accounts({
        materialAccount: materialKeypair.publicKey,
        initializer:      provider.wallet.publicKey,
        systemProgram:    SystemProgram.programId,
      })
      .signers([materialKeypair])
      .rpc();

    // 2) Perform the transfer to a new holder
    const newHolder = Keypair.generate();
    await program.methods
      .transferMaterial(newHolder.publicKey)
      .accounts({
        materialAccount: materialKeypair.publicKey,
        currentHolder:   provider.wallet.publicKey,
      })
      .rpc();

    // 3) Fetch and assert transfer
    const account = await program.account.material.fetch(materialKeypair.publicKey);
    assert.ok(account.currentHolder.equals(newHolder.publicKey));
    assert.equal(account.lastSequence.toNumber(), 1);
  });
});
