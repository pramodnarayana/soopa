import { Module } from '@nestjs/common';
import { ShardAllocatorService } from './services/shard-allocator.service.js';

@Module({
  imports: [],
  providers: [ShardAllocatorService],
  exports: [ShardAllocatorService],
})
export class ApplicationModule {}
