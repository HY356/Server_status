"""监控配置管理模块，处理不同监控模式的时间判断逻辑。"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class MonitorConfig:
    """监控配置管理类，支持三种监控模式：
    - CONTINUOUS: 持续监控（默认模式）
    - SCHEDULED: 定时监控（指定时间段和日期）
    - COUNTDOWN: 倒计时监控（运行指定时长后停止）
    """
    
    def __init__(self, config_data: Optional[Dict[str, Any]] = None):
        """初始化监控配置
        
        Args:
            config_data: 服务端返回的监控配置数据
        """
        if config_data is None:
            config_data = {}
        
        self.mode = config_data.get('mode', 'CONTINUOUS')
        self.schedule = config_data.get('schedule', {})
        self.countdown = config_data.get('countdown', {})
        self.last_update = datetime.now()
        
        logger.info("监控配置初始化: 模式=%s", self.mode)
        if self.mode == 'SCHEDULED':
            logger.info("定时监控配置: 时间=%s-%s, 日期=%s", 
                       self.schedule.get('start_time'), 
                       self.schedule.get('end_time'),
                       self.schedule.get('days'))
        elif self.mode == 'COUNTDOWN':
            logger.info("倒计时监控配置: 持续时间=%s分钟, 结束时间=%s",
                       self.countdown.get('duration'),
                       self.countdown.get('end_time'))
    
    def update_config(self, config_data: Dict[str, Any]) -> None:
        """更新监控配置
        
        Args:
            config_data: 新的监控配置数据
        """
        old_mode = self.mode
        self.mode = config_data.get('mode', 'CONTINUOUS')
        self.schedule = config_data.get('schedule', {})
        self.countdown = config_data.get('countdown', {})
        self.last_update = datetime.now()
        
        if old_mode != self.mode:
            logger.info("监控模式变更: %s -> %s", old_mode, self.mode)
        else:
            logger.debug("监控配置已更新")
    
    def is_monitoring_time(self) -> bool:
        """检查当前是否应该进行监控
        
        Returns:
            bool: True表示应该监控，False表示不应该监控
        """
        try:
            if self.mode == 'CONTINUOUS':
                return True
            elif self.mode == 'SCHEDULED':
                return self._check_scheduled_time()
            elif self.mode == 'COUNTDOWN':
                return self._check_countdown_time()
            else:
                logger.warning("未知的监控模式: %s，默认为持续监控", self.mode)
                return True
        except Exception as e:
            logger.error("检查监控时间时发生错误: %s", e)
            return True  # 出错时默认允许监控
    
    def _check_scheduled_time(self) -> bool:
        """检查定时监控时间
        
        Returns:
            bool: True表示在监控时间内，False表示不在监控时间内
        """
        if not self.schedule:
            logger.debug("定时监控配置为空，默认允许监控")
            return True
        
        now = datetime.now()
        current_weekday = str(now.weekday() + 1)  # 1=周一, 7=周日
        current_time = now.strftime('%H:%M')
        
        # 检查是否在监控日期内
        days = self.schedule.get('days', [])
        if days and current_weekday not in days:
            logger.debug("当前日期(%s)不在监控日期内(%s)", current_weekday, days)
            return False
        
        # 检查是否在监控时间内
        start_time = self.schedule.get('start_time')
        end_time = self.schedule.get('end_time')
        
        if start_time and end_time:
            if start_time <= current_time <= end_time:
                logger.debug("当前时间(%s)在监控时间内(%s-%s)", current_time, start_time, end_time)
                return True
            else:
                logger.debug("当前时间(%s)不在监控时间内(%s-%s)", current_time, start_time, end_time)
                return False
        
        # 如果没有配置时间范围，默认允许监控
        logger.debug("未配置监控时间范围，默认允许监控")
        return True
    
    def _check_countdown_time(self) -> bool:
        """检查倒计时监控时间
        
        Returns:
            bool: True表示倒计时未结束，False表示倒计时已结束
        """
        if not self.countdown:
            logger.debug("倒计时监控配置为空，默认不允许监控")
            return False
        
        end_time_str = self.countdown.get('end_time')
        if not end_time_str:
            logger.debug("倒计时监控未配置结束时间，默认不允许监控")
            return False
        
        try:
            # 解析结束时间，支持多种格式
            if end_time_str.endswith('Z'):
                # UTC时间格式
                end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                current_time = datetime.now(timezone.utc)
            else:
                # 本地时间格式
                end_time = datetime.fromisoformat(end_time_str)
                current_time = datetime.now()
            
            is_active = current_time < end_time
            if is_active:
                remaining = end_time - current_time
                logger.debug("倒计时监控活跃，剩余时间: %s", remaining)
            else:
                logger.debug("倒计时监控已结束")
            
            return is_active
            
        except Exception as e:
            logger.error("解析倒计时结束时间失败: %s, 错误: %s", end_time_str, e)
            return False
    
    def get_status_info(self) -> Dict[str, Any]:
        """获取当前监控状态信息
        
        Returns:
            Dict: 包含监控状态的详细信息
        """
        info = {
            'mode': self.mode,
            'is_monitoring_time': self.is_monitoring_time(),
            'last_update': self.last_update.isoformat()
        }
        
        if self.mode == 'SCHEDULED':
            info['schedule'] = self.schedule.copy()
            if self.schedule:
                now = datetime.now()
                info['current_weekday'] = str(now.weekday() + 1)
                info['current_time'] = now.strftime('%H:%M')
        
        elif self.mode == 'COUNTDOWN':
            info['countdown'] = self.countdown.copy()
            if self.countdown.get('end_time'):
                try:
                    end_time_str = self.countdown['end_time']
                    if end_time_str.endswith('Z'):
                        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))
                        current_time = datetime.now(timezone.utc)
                    else:
                        end_time = datetime.fromisoformat(end_time_str)
                        current_time = datetime.now()
                    
                    if current_time < end_time:
                        remaining = end_time - current_time
                        info['remaining_seconds'] = int(remaining.total_seconds())
                    else:
                        info['remaining_seconds'] = 0
                except Exception as e:
                    logger.error("计算剩余时间失败: %s", e)
                    info['remaining_seconds'] = 0
        
        return info
